# SPDX-License-Identifier: BSD-3-Clause
cmake_minimum_required(VERSION 3.20)
project(kettle-power-applet VERSION 1.1.0 LANGUAGES CXX)

find_package(ECM 6.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.7 REQUIRED COMPONENTS Core DBus Qml Quick Widgets)
find_package(KF6 6.5 REQUIRED COMPONENTS Config)

qt_policy(SET QTP0001 NEW)
qt_standard_project_setup(REQUIRES 6.7)

# the applet's and the Performance app's backend: kettle-powerd on the system bus, and the
# readings it doesn't give (the game's frame rate, temperatures, memory), and the bottom screen
include(ECMQmlModule)
ecm_add_qml_module(kettlepowerplugin URI org.kettle.private.power GENERATE_PLUGIN_SOURCE)
target_sources(kettlepowerplugin PRIVATE
    src/powerbackend.cpp src/powerbackend.h
    src/gamestats.cpp src/gamestats.h
    src/systemstats.cpp src/systemstats.h
    src/bottomscreen.cpp src/bottomscreen.h)
target_include_directories(kettlepowerplugin PRIVATE src)
target_link_libraries(kettlepowerplugin PRIVATE Qt6::Core Qt6::DBus Qt6::Qml KF6::ConfigCore)
ecm_finalize_qml_module(kettlepowerplugin DESTINATION ${KDE_INSTALL_QMLDIR})

# the applet itself (a Plasma package: metadata.json + QML)
install(DIRECTORY package/ DESTINATION ${KDE_INSTALL_DATADIR}/plasma/plasmoids/org.kettle.power)

# the Performance app (the Thor's bottom screen in Game Mode, and a window in Desktop Mode)
add_subdirectory(app)
