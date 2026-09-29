# SPDX-License-Identifier: BSD-3-Clause
cmake_minimum_required(VERSION 3.20)
project(kettle-welcome VERSION 2.0.0 LANGUAGES CXX)

find_package(ECM 6.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.7 REQUIRED COMPONENTS Core Gui Network Qml Quick QuickControls2 Widgets)
find_package(KF6 6.5 REQUIRED COMPONENTS CoreAddons Config DBusAddons KIO Service WindowSystem)

# where welcome-flatpak lives, and the window icon (the Plasma splash's kettle)
set(KETTLE_LIBDIR "${CMAKE_INSTALL_PREFIX}/lib/kettle" CACHE PATH "Directory with welcome-flatpak")
set(KETTLE_ICON "/usr/share/plasma/look-and-feel/org.kettle.splash/contents/splash/images/kettle.png" CACHE FILEPATH "Window icon")

qt_policy(SET QTP0001 NEW)
qt_standard_project_setup(REQUIRES 6.7)

add_executable(kettle-welcome src/main.cpp src/backend.cpp)
target_compile_definitions(kettle-welcome PRIVATE
    KETTLE_VERSION="${PROJECT_VERSION}" KETTLE_LIBDIR="${KETTLE_LIBDIR}" KETTLE_ICON="${KETTLE_ICON}")

set_source_files_properties(src/qml/Constants.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(kettle-welcome
    URI org.kettle.welcome
    VERSION 1.0
    QML_FILES
        src/qml/Main.qml
        src/qml/Constants.qml
        src/qml/BasePage.qml
        src/qml/Section.qml
        src/qml/Tile.qml
        src/qml/TileGrid.qml
        src/qml/HomePage.qml
        src/qml/SetupPage.qml
        src/qml/ControlsPage.qml
        src/qml/GamesPage.qml
        src/qml/AndroidPage.qml
        src/qml/ExtrasPage.qml
        src/qml/SystemPage.qml
)

target_link_libraries(kettle-welcome PRIVATE
    Qt6::Network Qt6::Quick Qt6::Qml Qt6::QuickControls2 Qt6::Widgets
    KF6::CoreAddons KF6::ConfigCore KF6::DBusAddons KF6::KIOGui KF6::Service KF6::WindowSystem)

install(TARGETS kettle-welcome ${KDE_INSTALL_TARGETS_DEFAULT_ARGS})
install(PROGRAMS welcome-flatpak DESTINATION ${KETTLE_LIBDIR})
install(FILES org.kettle.Welcome.desktop org.kettle.GamingExtras.desktop DESTINATION ${KDE_INSTALL_APPDIR})
install(FILES org.kettle.Welcome.autostart.desktop DESTINATION ${KDE_INSTALL_AUTOSTARTDIR} RENAME org.kettle.Welcome.desktop)
# a shortcut on the Plasma desktop, next to steamdeck-kde-presets' Return to Gaming Mode: new home
# directories get it from /etc/skel (executable, so Plasma runs it without asking)
install(PROGRAMS org.kettle.Welcome.desktop DESTINATION /etc/skel/Desktop RENAME Welcome.desktop)
