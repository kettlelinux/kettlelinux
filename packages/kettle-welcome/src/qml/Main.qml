// SPDX-License-Identifier: BSD-3-Clause
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.welcome

Kirigami.ApplicationWindow {
    id: root

    title: "Kettle Welcome"
    width: Kirigami.Units.gridUnit * 64
    height: Kirigami.Units.gridUnit * 40
    minimumWidth: Kirigami.Units.gridUnit * 36
    minimumHeight: Kirigami.Units.gridUnit * 24
    visibility: Backend.screenshotDir.length > 0 ? Window.Windowed : Window.Maximized

    readonly property var pages: [
        { name: "home", title: "Welcome", icon: "go-home", component: homePage },
        { name: "setup", title: "Setup", icon: "configure", component: setupPage },
        { name: "controls", title: "Controls", icon: "input-gamepad", component: controlsPage },
        { name: "games", title: "Games", icon: "applications-games", component: gamesPage },
        { name: "android", title: "Android", icon: "smartphone", component: androidPage },
        { name: "extras", title: "Gaming Extras", icon: "download", component: extrasPage },
        { name: "system", title: "System", icon: "computer", component: systemPage }
    ].filter(p => p.name !== "android" || Backend.hasAndroidGames)  // Android: with kettle-lepton
    property string currentPage: ""

    function showPage(name) {
        const page = pages.find(p => p.name === name) || pages[0];
        if (page.name === currentPage) {
            return;
        }
        currentPage = page.name;
        pageStack.clear();
        pageStack.push(page.component);
    }

    Connections {
        target: Backend
        function onPageRequested(page) { root.showPage(page) }
    }

    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    pageStack.columnView.columnResizeMode: Kirigami.ColumnView.SingleColumn

    globalDrawer: Kirigami.GlobalDrawer {
        id: drawer
        modal: !root.wideScreen
        handleVisible: modal
        width: Kirigami.Units.gridUnit * 13
        isMenu: false
        showHeaderWhenCollapsed: true

        header: ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            Image {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                Layout.preferredHeight: Layout.preferredWidth
                source: "file://" + Constants.kettleArt
                fillMode: Image.PreserveAspectFit
                visible: status === Image.Ready
            }
            Kirigami.Heading {
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
                text: "Kettle Linux"
                level: 2
            }
        }

        actions: root.pages.map(p => pageAction.createObject(drawer, { page: p }))

        Component {
            id: pageAction
            Kirigami.Action {
                required property var page
                text: page.title
                icon.name: page.icon
                checkable: true
                checked: root.currentPage === page.name
                onTriggered: {
                    root.showPage(page.name);
                    if (drawer.modal) {
                        drawer.close();
                    }
                }
            }
        }
    }

    Component { id: homePage; HomePage { onNavigate: name => root.showPage(name) } }
    Component { id: setupPage; SetupPage {} }
    Component { id: controlsPage; ControlsPage {} }
    Component { id: gamesPage; GamesPage { onNavigate: name => root.showPage(name) } }
    Component { id: androidPage; AndroidPage {} }
    Component { id: extrasPage; ExtrasPage {} }
    Component { id: systemPage; SystemPage {} }

    Component.onCompleted: {
        showPage(startPage);
        if (Backend.screenshotDir.length > 0) {
            shots.start();
        }
    }

    // --screenshot DIR: every page as DIR/<page>.png, then quit
    Timer {
        id: shots
        property int index: -1
        interval: 1500
        repeat: true
        onTriggered: {
            if (index >= 0) {
                Backend.saveScreenshot(root, root.pages[index].name);
            }
            index++;
            if (index >= root.pages.length) {
                Qt.quit();
                return;
            }
            root.showPage(root.pages[index].name);
        }
    }
}
