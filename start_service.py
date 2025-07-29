#!/usr/bin/env python3
"""
代码沙箱服务启动脚本
提供更好的日志控制和启动选项
"""

import argparse
import logging
import uvicorn
import sys

def setup_logging(log_level: str, quiet_mode: bool = False):
    """设置日志配置"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # 基础日志格式
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if quiet_mode:
        # 静默模式：只显示ERROR级别以上的日志
        logging.getLogger().setLevel(logging.ERROR)
        logging.getLogger('uvicorn').setLevel(logging.ERROR)
        logging.getLogger('uvicorn.access').setLevel(logging.ERROR)
        logging.getLogger('apscheduler').setLevel(logging.ERROR)
    else:
        # 正常模式：降低第三方库日志级别
        logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
        logging.getLogger('apscheduler').setLevel(logging.WARNING)

def main():
    parser = argparse.ArgumentParser(description='代码沙箱服务')
    parser.add_argument('--host', default='0.0.0.0', help='服务监听地址')
    parser.add_argument('--port', type=int, default=8000, help='服务端口')
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别')
    parser.add_argument('--quiet', action='store_true', help='静默模式（只显示错误日志）')
    parser.add_argument('--reload', action='store_true', help='开发模式（文件变更自动重载）')
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.log_level, args.quiet)
    
    logger = logging.getLogger(__name__)
    
    if args.quiet:
        print(f"🚀 代码沙箱服务启动中... (静默模式)")
        print(f"📍 服务地址: http://{args.host}:{args.port}")
        print(f"📖 API文档: http://{args.host}:{args.port}/docs")
    else:
        logger.info("🚀 启动代码沙箱服务...")
        logger.info(f"📍 服务地址: http://{args.host}:{args.port}")
        logger.info(f"📖 API文档: http://{args.host}:{args.port}/docs")
    
    try:
        uvicorn.run(
            "service:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level.lower() if not args.quiet else "error",
            access_log=not args.quiet
        )
    except KeyboardInterrupt:
        if not args.quiet:
            logger.info("👋 服务已停止")
        else:
            print("👋 服务已停止")
    except Exception as e:
        if not args.quiet:
            logger.error(f"❌ 服务启动失败: {e}")
        else:
            print(f"❌ 服务启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 