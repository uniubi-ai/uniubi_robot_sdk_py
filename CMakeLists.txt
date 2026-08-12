# Motion SDK Python 绑定
# 由 pip install / scikit-build-core 直接调用（独立 wheel 构建）。
# 通过 UNIUBI_SDK_ROOT 指向 uniubi_robot_sdk 仓库或安装前缀。
# pybind11 头已 vendor 到 ThirdParty/pybind11/include/，不依赖外部 pybind11

cmake_minimum_required(VERSION 3.18)

project(uniubi_robot_motion_sdk_python
    VERSION 0.1.0
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
    set(UNIUBI_SDK_ARCH_DIR "x86_64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64|ARM64)$")
    set(UNIUBI_SDK_ARCH_DIR "aarch64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(i.86|x86)$")
    set(UNIUBI_SDK_ARCH_DIR "i386")
else()
    message(FATAL_ERROR "Unsupported CMAKE_SYSTEM_PROCESSOR='${CMAKE_SYSTEM_PROCESSOR}'; expected x86_64 / aarch64 / i386")
endif()

if(NOT DEFINED UNIUBI_SDK_ENABLE_MEDIA)
    if(UNIUBI_SDK_ARCH_DIR STREQUAL "x86_64" OR UNIUBI_SDK_ARCH_DIR STREQUAL "i386")
        set(UNIUBI_SDK_ENABLE_MEDIA OFF)
    else()
        set(UNIUBI_SDK_ENABLE_MEDIA ON)
    endif()
endif()
message(STATUS "Uniubi Python SDK media bindings: ${UNIUBI_SDK_ENABLE_MEDIA}")

# 闭源 SDK 共享库：按 CMAKE_SYSTEM_PROCESSOR 选 lib/<arch>/
if(NOT UNIUBI_ROBOT_MOTION_SDK_LIB)
    if(NOT UNIUBI_SDK_ROOT AND DEFINED ENV{UNIUBI_SDK_ROOT})
        set(UNIUBI_SDK_ROOT $ENV{UNIUBI_SDK_ROOT})
    endif()

    find_library(UNIUBI_ROBOT_MOTION_SDK_LIB
        NAMES robotMotionSdk
        HINTS ${UNIUBI_SDK_ROOT}/lib/${UNIUBI_SDK_ARCH_DIR}
              ${CMAKE_CURRENT_SOURCE_DIR}/../uniubi_robot_sdk/lib/${UNIUBI_SDK_ARCH_DIR}
              /opt/uniubi/lib/${UNIUBI_SDK_ARCH_DIR}
        NO_DEFAULT_PATH
        NO_CMAKE_FIND_ROOT_PATH
        REQUIRED)
endif()

if(UNIUBI_SDK_ENABLE_MEDIA AND NOT UNIUBI_MEDIABUS_LIB)
    find_library(UNIUBI_MEDIABUS_LIB
        NAMES mediaBus
        HINTS ${UNIUBI_SDK_ROOT}/lib/${UNIUBI_SDK_ARCH_DIR}
              ${CMAKE_CURRENT_SOURCE_DIR}/../uniubi_robot_sdk/lib/${UNIUBI_SDK_ARCH_DIR}
              /opt/uniubi/lib/${UNIUBI_SDK_ARCH_DIR}
        NO_DEFAULT_PATH
        NO_CMAKE_FIND_ROOT_PATH
        REQUIRED)
endif()

# 公开头根：父级未提供则默认指向同级 uniubi_robot_sdk/include
if(NOT UNIUBI_SDK_INCLUDE_DIR)
    if(UNIUBI_SDK_ROOT)
        set(UNIUBI_SDK_INCLUDE_DIR ${UNIUBI_SDK_ROOT}/include CACHE PATH "Uniubi SDK public headers root")
    else()
        set(UNIUBI_SDK_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../uniubi_robot_sdk/include CACHE PATH "Uniubi SDK public headers root")
    endif()
endif()

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)

set(UNIUBI_PY_BINDING_SOURCES src/MotionSdkPython.cpp)
if(UNIUBI_SDK_ENABLE_MEDIA)
    list(APPEND UNIUBI_PY_BINDING_SOURCES src/MediaFrameBindings.cpp)
endif()

add_library(_uniubi_robot_motion_py_native MODULE
    ${UNIUBI_PY_BINDING_SOURCES}
)

# pybind11 + Python 头列入 SYSTEM 抑制其内部 -Wall 警告
target_include_directories(_uniubi_robot_motion_py_native SYSTEM PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/ThirdParty/pybind11/include
    ${Python3_INCLUDE_DIRS}
)

# 仅依赖 SDK 公开面头，零内部头依赖
target_include_directories(_uniubi_robot_motion_py_native PRIVATE
    ${UNIUBI_SDK_INCLUDE_DIR}
)

target_link_libraries(_uniubi_robot_motion_py_native PRIVATE
    ${UNIUBI_ROBOT_MOTION_SDK_LIB}
)
if(UNIUBI_SDK_ENABLE_MEDIA)
    target_link_libraries(_uniubi_robot_motion_py_native PRIVATE ${UNIUBI_MEDIABUS_LIB})
endif()

target_compile_features(_uniubi_robot_motion_py_native PRIVATE cxx_std_14)
target_compile_definitions(_uniubi_robot_motion_py_native PRIVATE UNIUBI_ROBOTSDK_PY_ENABLE_MEDIA=$<BOOL:${UNIUBI_SDK_ENABLE_MEDIA}>)

# 计算 Python ABI 后缀（例 .cpython-310-x86_64-linux-gnu.so）；
# Python3_SOABI 由 find_package(Python3) 在 CMake 3.18+ 上提供
if(Python3_SOABI)
    set(PY_MODULE_SUFFIX ".${Python3_SOABI}.so")
else()
    set(PY_MODULE_SUFFIX ".so")
endif()

# 等价于 pybind11_add_module 的关键属性：无 lib 前缀、PIC、符号默认 hidden、ABI 后缀
set_target_properties(_uniubi_robot_motion_py_native PROPERTIES
    PREFIX ""
    SUFFIX "${PY_MODULE_SUFFIX}"
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# wheel 模式 (scikit-build-core)：DESTINATION 相对 wheel 根（即 site-packages），
# 装到 robot_motion_sdk/ 目录下；__init__.py 由 pyproject.toml 的 wheel.packages 负责打包
install(TARGETS _uniubi_robot_motion_py_native LIBRARY DESTINATION robot_motion_sdk)
