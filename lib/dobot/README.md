# Dobot SDK — Vendored Libraries

This directory contains the Dobot Magician SDK files required by `app/adapters/robot.py`.

## Contents

| File                                                                   | Platform | Purpose                                                 |
| :--------------------------------------------------------------------- | :------- | :------------------------------------------------------ |
| `DobotDllTypeMulti.py`                                                 | All      | Python ctypes wrapper (the module imported by robot.py) |
| `libDobotDll.dylib`                                                    | macOS    | Native shared library                                   |
| `DobotDll.dll`                                                         | Windows  | Native shared library                                   |
| `libDobotDll.so`                                                       | Linux    | Native shared library (users must provide)              |
| `Qt5Core.dll`, `Qt5Network.dll`, `Qt5SerialPort.dll`                   | Windows  | Qt runtime dependencies                                 |
| `msvcp120.dll`, `msvcr120.dll`                                         | Windows  | MSVC runtime dependencies                               |
| `QtCore.framework/`, `QtNetwork.framework/`, `QtSerialPort.framework/` | macOS    | Qt framework bundles                                    |

## Setup

The files originate from the **DobotDemoForPython** repository.

### macOS

```bash
cp DobotDemoForPython/DobotDllTypeMulti.py  lib/dobot/
cp DobotDemoForPython/libDobotDll.dylib     lib/dobot/
cp -R DobotDemoForPython/Qt*.framework      lib/dobot/
```

### Windows

```bash
copy DobotDemoForPython\DobotDllTypeMulti.py  lib\dobot\
copy DobotDemoForPython\DobotDll.dll          lib\dobot\
copy DobotDemoForPython\Qt5*.dll              lib\dobot\
copy DobotDemoForPython\msvc*.dll             lib\dobot\
```

### Linux

```bash
cp DobotDemoForPython/DobotDllTypeMulti.py  lib/dobot/
cp DobotDemoForPython/libDobotDll.so        lib/dobot/
```

> Linux users may need to build `libDobotDll.so` from the `demo-magician-qt-mutil-master` source if a pre-built binary is not available.

## How it works

`app/adapters/robot.py` adds `lib/dobot/` to `sys.path` at import time, so `import DobotDllTypeMulti` resolves to this directory. The `load()` function inside `DobotDllTypeMulti.py` uses `os.path.dirname(__file__)` to find the native library next to itself — that's why all platform binaries must live in this same folder.
