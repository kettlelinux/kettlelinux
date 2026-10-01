# SPDX-License-Identifier: BSD-3-Clause
qt_add_executable(kettle-performance main.cpp)
qt_add_qml_module(kettle-performance
    URI org.kettle.performance
    QML_FILES
        Main.qml
        StatsPage.qml
        SettingsPage.qml
        Tile.qml
        FrameGraph.qml
        SliderRow.qml
        SwitchRow.qml)
target_link_libraries(kettle-performance PRIVATE Qt6::Widgets Qt6::Quick Qt6::Qml)
install(TARGETS kettle-performance ${KDE_INSTALL_TARGETS_DEFAULT_ARGS})
install(FILES org.kettlelinux.Performance.desktop DESTINATION ${KDE_INSTALL_APPDIR})
