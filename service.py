import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from entities import (
    CodeExecutionRequest,
    ExecutionResult,
    ApiResponse,
    TaskSubmissionResponse,
    SecurityLevel,
    TaskStatus,
)
from executor_manager import ExecutorManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 降低第三方库的日志级别
logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 全局执行器管理器实例
executor_manager: Optional[ExecutorManager] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    global executor_manager
    
    # 启动时初始化
    logger.info("启动代码沙箱服务...")
    
    # TODO: Kubernetes配置
    # k8s_config = {
    #     "namespace": "code-sandbox",
    #     "api_server": "https://kubernetes.default.svc",
    #     "token": "/var/run/secrets/kubernetes.io/serviceaccount/token",
    #     "ca_cert": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    # }
    
    # 初始化执行器管理器
    executor_manager = ExecutorManager(k8s_config=None)  # 开发环境先不使用k8s
    
    # 启动执行器管理器
    await executor_manager.start()
    
    logger.info("代码沙箱服务启动完成")
    
    yield
    
    # 关闭时清理
    logger.info("关闭代码沙箱服务...")
    if executor_manager:
        await executor_manager.stop()
    logger.info("代码沙箱服务已关闭")

# 创建FastAPI应用
app = FastAPI(
    title="代码沙箱服务",
    description="支持多种编程语言的安全代码执行服务",
    version="0.10.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO:生产环境中应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "服务器内部错误",
            "data": None
        }
    )

@app.get("/")
async def root():
    """根路径健康检查"""
    return ApiResponse[Dict[str, str]](
        success=True,
        message="代码沙箱服务运行正常",
        data={"service": "euler-copilot-sandbox", "status": "running"}
    )

@app.get("/health")
async def health_check():
    """健康检查接口"""
    if not executor_manager or not executor_manager._is_running:
        raise HTTPException(
            status_code=503,
            detail="服务不可用"
        )
    
    return ApiResponse[Dict[str, Any]](
        success=True,
        message="服务健康",
        data=executor_manager.get_system_status()
    )

@app.post("/execute", response_model=ApiResponse[TaskSubmissionResponse])
async def submit_code_execution(request: CodeExecutionRequest, priority: int = 0):
    """
    提交代码执行任务
    
    Args:
        request: 代码执行请求
        priority: 任务优先级（数字越大优先级越高）
    
    Returns:
        任务提交响应
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        # 验证请求参数
        if not request.code.strip():
            raise HTTPException(
                status_code=400,
                detail="代码内容不能为空"
            )
        
        # 提交任务到队列
        task_id = await executor_manager.submit_task(request, priority)
        
        # 获取队列信息估算等待时间
        queue_info = executor_manager.get_queue_info()
        security_level_queue = queue_info["queues"].get(request.security_level.value, {})
        queue_size = security_level_queue.get("queue_size", 0)
        
        # 估算等待时间（简化计算）
        estimated_wait_time = queue_size * 10  # TODO:当前假设每个任务平均10秒，后续考虑基于经验预测
        
        logger.info(f"任务 {task_id} 已提交，安全等级: {request.security_level.value}")
        
        return ApiResponse[TaskSubmissionResponse](
            success=True,
            message="任务提交成功",
            data=TaskSubmissionResponse(
                task_id=task_id,
                estimated_wait_time=estimated_wait_time,
                queue_position=queue_size + 1
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交代码执行任务失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"提交任务失败: {str(e)}"
        )

@app.get("/task/{task_id}/status")
async def get_task_status(task_id: str):
    """
    获取任务状态
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务状态信息
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        status = await executor_manager.get_task_status(task_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail="任务不存在"
            )
        
        return ApiResponse[Dict[str, str]](
            success=True,
            message="获取任务状态成功",
            data={"task_id": task_id, "status": status}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取任务状态失败: {str(e)}"
        )

@app.get("/task/{task_id}/result", response_model=ApiResponse[ExecutionResult])
async def get_task_result(task_id: str):
    """
    获取任务执行结果
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务执行结果
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        result = await executor_manager.get_task_result(task_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="任务结果不存在"
            )
        
        return ApiResponse[ExecutionResult](
            success=True,
            message="获取任务结果成功",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务结果失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取任务结果失败: {str(e)}"
        )

@app.get("/status/{task_id}", response_model=ApiResponse[ExecutionResult])
async def get_task_status_legacy(task_id: str):
    """
    获取任务状态和结果（向后兼容接口）
    
    Args:
        task_id: 任务ID
    
    Returns:
        任务执行结果
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        # 获取任务状态
        status = await executor_manager.get_task_status(task_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail="任务不存在"
            )
        
        # 获取任务结果
        result = await executor_manager.get_task_result(task_id)
        if result is None:
            # 如果没有结果，创建一个基本的状态响应
            result = ExecutionResult(
                task_id=task_id,
                status=TaskStatus(status),
                output=None,
                error=None,
                return_code=None,
                execution_time=None,
                memory_usage=None,
                cpu_usage=None,
                start_time=None,
                end_time=None
            )
        
        return ApiResponse[ExecutionResult](
            success=True,
            message="获取任务状态成功",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取任务状态失败: {str(e)}"
        )

@app.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """
    取消任务
    
    Args:
        task_id: 任务ID
    
    Returns:
        取消结果
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        success = await executor_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail="任务无法取消（可能已在执行中或不存在）"
            )
        
        return ApiResponse[Dict[str, str]](
            success=True,
            message="任务取消成功",
            data={"task_id": task_id, "status": "cancelled"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"取消任务失败: {str(e)}"
        )

@app.get("/queues/info")
async def get_queue_info():
    """
    获取队列信息
    
    Returns:
        所有队列的状态信息
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        queue_info = executor_manager.get_queue_info()
        
        return ApiResponse[Dict[str, Any]](
            success=True,
            message="获取队列信息成功",
            data=queue_info
        )
        
    except Exception as e:
        logger.error(f"获取队列信息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取队列信息失败: {str(e)}"
        )

@app.get("/executors/status")
async def get_executor_status():
    """
    获取执行器状态
    
    Returns:
        所有执行器的状态信息
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        executor_status = executor_manager.get_executor_status()
        
        return ApiResponse[Dict[str, Any]](
            success=True,
            message="获取执行器状态成功",
            data=executor_status
        )
        
    except Exception as e:
        logger.error(f"获取执行器状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取执行器状态失败: {str(e)}"
        )

@app.get("/system/status")
async def get_system_status():
    """
    获取系统整体状态
    
    Returns:
        系统状态信息
    """
    try:
        if not executor_manager:
            raise HTTPException(
                status_code=503,
                detail="执行器管理器未初始化"
            )
        
        system_status = executor_manager.get_system_status()
        
        return ApiResponse[Dict[str, Any]](
            success=True,
            message="获取系统状态成功",
            data=system_status
        )
        
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取系统状态失败: {str(e)}"
        )

# TODO: 生产环境关闭测试接口
@app.post("/debug/submit-test-task")
async def submit_test_task(security_level: SecurityLevel = SecurityLevel.LOW):
    """
    提交测试任务（调试用）
    
    Args:
        security_level: 安全等级
    
    Returns:
        任务提交结果
    """
    from entities import UserInfo, CodeType
    
    test_request = CodeExecutionRequest(
        code="print('Hello, World!')\nprint('代码沙箱测试')",
        code_type=CodeType.PYTHON,
        user_info=UserInfo(
            user_id="test_user",
            username="测试用户",
            permissions=["execute"]
        ),
        security_level=security_level,
        timeout_seconds=10,
        input_data=None,
    )
    
    return await submit_code_execution(test_request, priority=1)

if __name__ == "__main__":
    # 开发环境启动配置
    uvicorn.run(
        "service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 