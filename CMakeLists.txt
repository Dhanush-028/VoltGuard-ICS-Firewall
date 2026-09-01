cmake_minimum_required(VERSION 3.16)
project(VoltGuardQt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTORCC ON)

# Works with either Qt6 (what the current online installer offers) or
# Qt5 (what this was originally built/tested against) - whichever one is
# on your machine, this picks it up automatically.
find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets Charts)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets Charts)

add_executable(voltguard_qt
    src/main.cpp
    src/mainwindow.cpp
    src/mainwindow.h
)

target_link_libraries(voltguard_qt PRIVATE Qt${QT_VERSION_MAJOR}::Widgets Qt${QT_VERSION_MAJOR}::Charts)
