# filetype 替换 python-magic

python-magic 在 Windows 上依赖系统 libmagic，`pip install` 不会自动安装 DLL，导致本地开发环境不一致。我们决定用 `filetype` 库替换：纯 Python 实现，通过文件头魔数检测类型，无系统依赖，跨平台一致。项目只需检测 PDF/DOCX/TXT/MD 等少量类型，filetype 足够。WeasyPrint 保留（容器化测试）。详见迁移计划阶段 2.4。

**Considered Options**: python-magic / filetype（选定）。python-magic 检测精度更高但 Windows 依赖问题严重；filetype 纯 Python 零依赖，覆盖项目所需类型。
