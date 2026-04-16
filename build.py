"""
ARAM 海克斯助手 - 一键打包脚本
运行: python build.py
输出: dist/ARAMHelper/
"""
import subprocess
import shutil
import os
import sys


APP_NAME = "ARAMHelper"
ENTRY_POINT = "gui_launcher.py"
ICON_PATH = os.path.join("assets", "icon.ico")
DIST_DIR = os.path.join("dist", APP_NAME)


def check_dependencies():
    """检查打包依赖"""
    try:
        import PyInstaller
        print(f"✅ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("❌ PyInstaller 未安装。运行: pip install pyinstaller")
        return False

    if not os.path.exists(ENTRY_POINT):
        print(f"❌ 入口文件不存在: {ENTRY_POINT}")
        return False

    if not os.path.exists(ICON_PATH):
        print(f"⚠ 图标文件不存在: {ICON_PATH}，将使用默认图标")

    return True


def build():
    """执行 PyInstaller 打包"""
    print(f"\n{'='*50}")
    print(f"  打包 {APP_NAME}")
    print(f"  入口: {ENTRY_POINT}")
    print(f"  模式: --onedir (单目录)")
    print(f"{'='*50}\n")

    # 排除不需要的大型包 (Anaconda 环境中容易被拖进来)
    EXCLUDES = [
        "torch", "torchvision", "torchaudio",
        "scipy", "pandas", "matplotlib",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy",
        "IPython", "jupyter", "notebook", "nbformat", "nbconvert",
        "pytest", "black", "yapf", "jedi", "parso",
        "dask", "distributed", "numba", "llvmlite",
        "h5py", "tables", "sqlalchemy", "botocore", "boto3",
        "pyarrow", "openpyxl", "lxml",
        "docutils", "sphinx", "pygments",
        "zmq", "tornado",
        "lib2to3", "blib2to3",
        "nacl", "cloudpickle",
        "onnxruntime.transformers",  # 这个子包依赖 torch
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconsole",
        "--name", APP_NAME,
        "--noconfirm",       # 不确认覆盖
        "--clean",           # 清理缓存

        # 收集 rapidocr 完整包 (含 ONNX 模型)
        "--collect-all", "rapidocr_onnxruntime",

        # onnxruntime: 只收集数据文件和二进制, 不收集子模块 (避免拖入 torch)
        "--collect-data", "onnxruntime",
        "--collect-binaries", "onnxruntime",

        # 隐式导入
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "thefuzz",
        "--hidden-import", "rapidfuzz",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "scripts",
        "--hidden-import", "scripts.lcu_connector",
        "--hidden-import", "scripts.hero_scraper",
        "--hidden-import", "scripts.updater",
        "--hidden-import", "scripts.utils",

        ENTRY_POINT,
    ]

    # 添加排除项
    for pkg in EXCLUDES:
        cmd.insert(-1, "--exclude-module")
        cmd.insert(-1, pkg)

    # 添加图标
    if os.path.exists(ICON_PATH):
        cmd.insert(-1, "--icon")
        cmd.insert(-1, ICON_PATH)

    print("执行命令:")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
    if result.returncode != 0:
        print(f"\n❌ PyInstaller 打包失败 (exit code: {result.returncode})")
        return False

    print("\n✅ PyInstaller 打包完成")
    return True


def copy_runtime_files():
    """复制运行时需要的数据文件到 dist 目录"""
    print("\n--- 复制运行时文件 ---")

    # 复制 data/ 目录 (CSV, JSON - 用户可更新)
    src_data = "data"
    dst_data = os.path.join(DIST_DIR, "data")
    if os.path.exists(src_data):
        if os.path.exists(dst_data):
            shutil.rmtree(dst_data)
        shutil.copytree(src_data, dst_data)
        print(f"✅ data/ → {dst_data}")
    else:
        print(f"⚠ data/ 不存在，跳过")

    # 复制 assets/ 目录 (图标)
    src_assets = "assets"
    dst_assets = os.path.join(DIST_DIR, "assets")
    if os.path.exists(src_assets):
        if os.path.exists(dst_assets):
            shutil.rmtree(dst_assets)
        shutil.copytree(src_assets, dst_assets)
        print(f"✅ assets/ → {dst_assets}")
    else:
        print(f"⚠ assets/ 不存在，跳过")

    print("✅ 运行时文件复制完成")


def cleanup_bloat():
    """移除不必要的大型 DLL (CUDA/TensorRT/MKL 等)"""
    import glob
    internal = os.path.join(DIST_DIR, "_internal")
    if not os.path.exists(internal):
        return

    print("\n--- 清理不必要的大型文件 ---")

    patterns = [
        "onnxruntime/capi/onnxruntime_providers_cuda*",
        "onnxruntime/capi/onnxruntime_providers_tensorrt*",
        "nvinfer*", "nvcuda*", "cudnn*", "cublas*",
        "cufft*", "curand*", "cusparse*", "cusolver*",
        "mkl_*.dll",
        "cv2/opencv_videoio_ffmpeg*",
    ]

    freed = 0
    for pat in patterns:
        for f in glob.glob(os.path.join(internal, pat)):
            sz = os.path.getsize(f)
            freed += sz
            os.remove(f)

    if freed > 0:
        print(f"✅ 已清理 {freed / 1024 / 1024:.0f} MB 不必要的文件 (CUDA/MKL/ffmpeg)")


def print_summary():
    """打印打包结果摘要"""
    print(f"\n{'='*50}")
    print(f"  ✅ 打包完成!")
    print(f"{'='*50}")
    print(f"\n  输出目录: {os.path.abspath(DIST_DIR)}")
    print(f"  可执行文件: {os.path.join(DIST_DIR, APP_NAME + '.exe')}")

    # 计算目录大小
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(DIST_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    size_mb = total_size / (1024 * 1024)
    print(f"  总大小: {size_mb:.1f} MB")

    print(f"\n  分发方式: 将 {DIST_DIR}/ 整个文件夹打成 ZIP 发给用户")
    print(f"  用户使用: 解压后双击 {APP_NAME}.exe 即可运行\n")


def main():
    # 修复 Windows 控制台编码
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    os.system('chcp 65001 >nul 2>&1')

    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")

    if not check_dependencies():
        return

    if not build():
        return

    copy_runtime_files()
    cleanup_bloat()
    print_summary()


if __name__ == "__main__":
    main()
