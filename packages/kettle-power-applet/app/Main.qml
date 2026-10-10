// SPDX-License-Identifier: BSD-3-Clause
// Performance: a Stats tab (power, clocks, temperatures, fan, memory, battery and the game's
// frame rate), a Settings tab (Steam's power values, Auto TDP, fan and CPU, charging, the
// screens' refresh rates and the bottom screen's brightness) and, in Game Mode, Trackpad and Keyboard tabs (a mouse and a keyboard for the top
// screen). Sized for the Thor's bottom screen (1240x1080 at 2x: 620x540).
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
    // one page: no swiping between pages, which took the Trackpad tab's drags from it
    pageStack.interactive: false
    pageStack.initialPage: Kirigami.Page {
        padding: 0
        topPadding: 0
        bottomPadding: 0

        StackLayout {
            anchors.fill: parent
            // the Trackpad and Keyboard tabs are Game Mode's only
            currentIndex: window.gameMode ? prefs.tab : Math.min(prefs.tab, 1)

            StatsPage {
                power: powerBackend
                system: systemStats
                game: gameStats
            }
            SettingsPage {
                power: powerBackend
                game: gameStats
                bottomScreen: bottomScreenSetting
                refreshRate: topRefreshRate
                gameMode: window.gameMode
                interval: prefs.interval
                onIntervalPicked: ms => prefs.interval = ms
                trackpadSpeed: prefs.trackpadSpeed
                onTrackpadSpeedPicked: speed => prefs.trackpadSpeed = speed
            }
            TrackpadPage {
                trackpad: trackpadMouse
                speed: prefs.trackpadSpeed
            }
            KeyboardPage {
                keyboard: keyboardKeys
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
                text: "Trackpad"
                icon.name: "input-touchpad"
                visible: window.gameMode
                checked: prefs.tab === 2
                onTriggered: prefs.tab = 2
            },
            Kirigami.Action {
                text: "Keyboard"
                icon.name: "input-keyboard"
                visible: window.gameMode
                checked: prefs.tab === 3
                onTriggered: prefs.tab = 3
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
        // the page shown: 0 Stats, 1 Settings, 2 Trackpad, 3 Keyboard (the stack's order; the tab
        // bar has Settings last)
        property int tab: 0
        // how often the readings update, ms
        property int interval: 1000
        // the Trackpad tab's pointer speed: top-screen pixels per bottom-screen pixel moved
        property real trackpadSpeed: 6
    }

    // the window can be seen: not minimized or hidden (Desktop Mode)
    readonly property bool shown: visibility !== Window.Minimized && visibility !== Window.Hidden

    // While Steam has dimmed the screens for idleness, nobody is reading these: they stop, and
    // with them this window's redraws, each of which the bottom screen's KWin and gamescope
    // composite again (about 0.07 W on the Thor). They read at once when the screens come back.
    PowerBackend {
        id: powerBackend
        mode: window.gameMode ? PowerBackend.GameMode : PowerBackend.Desktop
        // minimized, only kept in step with kettle-powerd (each status read has it measure the
        // draw for a while, a few firmware reads a second)
        interval: window.shown ? prefs.interval : 60000
        active: !bottomScreenSetting.dimmed
    }
    // only the Stats tab shows these (its battery readings are firmware round trips on the AYNs)
    SystemStats {
        id: systemStats
        interval: prefs.interval
        active: !bottomScreenSetting.dimmed && window.shown && prefs.tab === 0
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
    // the top screen's refresh rate (Game Mode): all games', and the running game's own
    RefreshRate {
        id: topRefreshRate
        activeGame: powerBackend.activeGame
    }
    // the mouse exists only while its tab is open (and the screens aren't dimmed)
    Trackpad {
        id: trackpadMouse
        active: window.gameMode && prefs.tab === 2 && !bottomScreenSetting.dimmed
    }
    // and the keyboard while its tab is
    Keyboard {
        id: keyboardKeys
        active: window.gameMode && prefs.tab === 3 && !bottomScreenSetting.dimmed
    }
}
