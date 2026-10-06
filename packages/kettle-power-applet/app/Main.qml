// SPDX-License-Identifier: BSD-3-Clause
// Performance: a Stats tab (power, clocks, temperatures, fan, memory, battery and the game's
// frame rate) and a Settings tab (Steam's power values, fan and CPU, the bottom screen's
// brightness). Sized for the Thor's bottom screen (1240x1080 at 2x: 620x540).
import QtCore
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.private.power

Kirigami.ApplicationWindow {
    id: window

    // next to Steam in Game Mode: follow the running game (main.cpp)
    required property bool gameMode

    title: "Performance"
    width: Kirigami.Units.gridUnit * 36
    height: Kirigami.Units.gridUnit * 30
    minimumWidth: Kirigami.Units.gridUnit * 16
    minimumHeight: Kirigami.Units.gridUnit * 16

    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    pageStack.initialPage: Kirigami.Page {
        padding: 0
        topPadding: 0
        bottomPadding: 0

        StackLayout {
            anchors.fill: parent
            currentIndex: prefs.tab

            StatsPage {
                power: powerBackend
                system: systemStats
                game: gameStats
            }
            SettingsPage {
                power: powerBackend
                game: gameStats
                bottomScreen: bottomScreenSetting
                gameMode: window.gameMode
                interval: prefs.interval
                onIntervalPicked: ms => prefs.interval = ms
            }
        }
    }

    footer: Kirigami.NavigationTabBar {
        actions: [
            Kirigami.Action {
                text: "Stats"
                icon.name: "speedometer"
                checked: prefs.tab === 0
                onTriggered: prefs.tab = 0
            },
            Kirigami.Action {
                text: "Settings"
                icon.name: "configure"
                checked: prefs.tab === 1
                onTriggered: prefs.tab = 1
            }
        ]
    }

    Settings {
        id: prefs
        property int tab: 0
        // how often the readings update, ms
        property int interval: 1000
    }

    // While Steam has dimmed the screens for idleness, nobody is reading these: they stop, and
    // with them this window's redraws, each of which the bottom screen's KWin and gamescope
    // composite again (about 0.07 W on the Thor). They read at once when the screens come back.
    PowerBackend {
        id: powerBackend
        mode: window.gameMode ? PowerBackend.GameMode : PowerBackend.Desktop
        interval: prefs.interval
        active: !bottomScreenSetting.dimmed
    }
    SystemStats {
        id: systemStats
        interval: prefs.interval
        active: !bottomScreenSetting.dimmed
    }
    GameStats {
        id: gameStats
        // mangoapp writes about once a second: read at twice that to show it soon after
        interval: 500
        active: !bottomScreenSetting.dimmed
    }
    BottomScreen {
        id: bottomScreenSetting
    }
}
