// SPDX-License-Identifier: BSD-3-Clause
// The Settings tab: the same controls as Quick Access > Performance (Steam's values, shared with
// Steam), Game Settings (fan and CPU, per game) and Device Settings > Screens (the bottom
// screen's brightness), all through the same settings, so each shows what the others set.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

QQC2.ScrollView {
    id: page

    required property var power // PowerBackend
    required property var game // GameStats
    required property var bottomScreen // BottomScreen
    required property bool gameMode
    // how often the readings update, ms
    required property int interval
    // the Trackpad tab's pointer speed (Game Mode)
    required property real trackpadSpeed

    signal intervalPicked(int ms)
    signal trackpadSpeedPicked(real speed)

    readonly property var info: power.info
    readonly property var status: power.status
    readonly property var steam: status.steam ?? ({})
    readonly property var fan: power.settings.fan ?? ({})
    readonly property var cpu: power.settings.cpu ?? ({})
    readonly property bool ready: power.available && info.profiles !== undefined
                                  && steam.profile !== undefined && fan.mode !== undefined
    readonly property var clusters: info.clusters ?? []
    readonly property int midCount: (clusters.find(c => c.name === "mid") ?? {cpus: []}).cpus.length
    readonly property bool hasPrime: clusters.some(c => c.name === "prime")
    // fixed GPU clocks on offer: the GPU's frequencies within kettle-powerd's range
    readonly property var gpuSteps: {
        const all = info.gpu_mhz ?? [];
        const range = info.gpu_manual_mhz ?? [all[0], all[all.length - 1]];
        return all.filter(f => f >= range[0] && f <= range[1]);
    }
    readonly property var clusterLabel: ({little: "Efficiency cores", mid: "Performance cores", prime: "Prime core"})
    // Game Mode: the running game (Device Settings tells kettle-powerd which it is)
    readonly property bool hasGame: gameMode && power.activeGame !== ""
    readonly property string gameName: !hasGame ? ""
        : game.appid === power.activeGame && game.name ? game.name
        : game.nameOf(power.activeGame) || "This game"

    QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
    contentWidth: availableWidth

    function mhz(khz) {
        return khz ? Math.round(khz / 1000) + " MHz" : "off";
    }

    // the fan and CPU settings shown, with a change in fan or cpu
    function update(patch) {
        power.setSettings({
            fan: Object.assign({}, fan, patch.fan ?? {}),
            cpu: Object.assign({}, cpu, patch.cpu ?? {}),
        });
    }

    // curve points stay in order: raising a point raises the ones after it, lowering lowers the ones before
    function setPoint(curve, i, pct) {
        return curve.map((pt, j) => [pt[0], j === i ? pct : j > i ? Math.max(pt[1], pct) : Math.min(pt[1], pct)]);
    }

    ColumnLayout {
        x: Kirigami.Units.largeSpacing
        width: page.availableWidth - Kirigami.Units.largeSpacing * 2
        spacing: Kirigami.Units.smallSpacing

        Item {
            implicitHeight: Kirigami.Units.smallSpacing
        }

        // --- the bottom screen (Game Mode on the Thor) ---

        Section {
            visible: page.bottomScreen.available
            text: "Bottom screen"
        }
        SliderRow {
            visible: page.bottomScreen.available
            text: "Brightness"
            from: 2
            to: 100
            value: page.bottomScreen.brightness
            valueText: Math.round(live) + "%"
            onPicked: v => page.bottomScreen.brightness = v
        }
        SliderRow {
            visible: page.gameMode
            text: "Trackpad speed"
            from: 1
            to: 15
            stepSize: 0.5
            value: page.trackpadSpeed
            valueText: live.toFixed(1) + "×"
            onPicked: v => page.trackpadSpeedPicked(v)
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit * 2
            visible: !page.ready
            icon.name: "speedometer"
            text: page.power.available ? "Reading the power settings…" : "The power service (kettle-powerd) isn't running"
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: page.ready
            spacing: Kirigami.Units.smallSpacing

            // --- Steam's values ---

            Section {
                text: "Performance"
            }
            QQC2.Label {
                Layout.fillWidth: true
                visible: page.gameMode
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: "The same settings as Steam's Performance panel. With a per-game profile on in Steam, "
                      + "Steam sets its own again when a game starts."
            }
            RowLayout {
                Layout.fillWidth: true

                Repeater {
                    // slowest first, as in Plasma's own power profiles
                    model: (page.info.profiles ?? []).slice().reverse()

                    QQC2.Button {
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1 // same width each
                        text: modelData
                        checkable: false
                        checked: page.steam.profile === modelData
                        onClicked: page.power.setSteam("profile", modelData)
                    }
                }
            }

            SliderRow {
                Layout.topMargin: Kirigami.Units.smallSpacing
                text: "Power limit (TDP)"
                from: page.info.tdp?.[0] ?? 0
                to: page.info.tdp?.[1] ?? 1
                value: page.steam.tdp ?? to
                valueText: live >= to ? "No limit" : live + " W"
                onPicked: v => page.power.setSteam("tdp", v)
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: "The whole device's draw, screens included."
            }

            SwitchRow {
                Layout.topMargin: Kirigami.Units.smallSpacing
                text: "Fixed GPU clock"
                value: page.steam.gpu_level === "manual"
                onPicked: on => page.power.setSteam("gpu_level", on ? "manual" : "auto")
            }
            SliderRow {
                visible: page.steam.gpu_level === "manual" && page.gpuSteps.length > 1
                text: "GPU clock"
                from: 0
                to: page.gpuSteps.length - 1
                value: Math.max(0, page.gpuSteps.filter(f => f <= page.steam.gpu_clock).length - 1)
                valueText: page.gpuSteps[live] + " MHz"
                onPicked: i => page.power.setSteam("gpu_clock", page.gpuSteps[i])
            }

            // --- fan and CPU: the running game's (Game Mode) or Desktop Mode's ---

            Section {
                text: "Fan and CPU"
            }
            SwitchRow {
                visible: page.hasGame
                text: "Settings for this game only"
                value: page.power.customSettings
                onPicked: on => page.power.setGameOnly(on)
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: !page.gameMode
                    ? (page.power.customSettings ? "Desktop Mode has its own fan and CPU settings. Game Mode keeps its own."
                                                 : "Game Mode's settings for all games, until you change one here.")
                    : page.hasGame && page.power.customSettings ? "Editing: " + page.gameName + " only"
                    : page.hasGame ? "Editing: all games (" + page.gameName + " has no settings of its own)"
                    : "Editing: all games"
            }

            QQC2.ComboBox {
                id: fanMode
                readonly property var modes: ["auto", "curve", "fixed"]
                Layout.fillWidth: true
                visible: page.info.fan === true
                model: ["Fan: automatic (built-in curve)", "Fan: custom curve", "Fan: fixed speed"]
                currentIndex: modes.indexOf(page.fan.mode)
                onActivated: index => {
                    page.update({fan: {mode: modes[index]}});
                    currentIndex = Qt.binding(() => modes.indexOf(page.fan.mode));
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: page.info.fan === true && page.fan.mode !== "auto" && page.steam.fan_control === 0

                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "Fan control is off in Steam's settings, so the built-in curve runs."
                }
                QQC2.Button {
                    text: "Turn On"
                    onClicked: page.power.setSteam("fan_control", 1)
                }
            }
            SliderRow {
                visible: page.info.fan === true && page.fan.mode === "fixed"
                text: "Fan speed"
                from: 0
                to: 100
                stepSize: 5
                value: page.fan.fixed ?? 50
                valueText: live + "%"
                onPicked: v => page.update({fan: {fixed: v}})
            }
            Repeater {
                model: page.info.fan === true && page.fan.mode === "curve" ? page.fan.curve : []

                SliderRow {
                    required property var modelData
                    required property int index
                    text: "At " + modelData[0] + " °C"
                    from: 0
                    to: 100
                    stepSize: 5
                    value: modelData[1]
                    valueText: live + "%"
                    onPicked: v => page.update({fan: {curve: page.setPoint(page.fan.curve, index, v)}})
                }
            }
            QQC2.Label {
                Layout.fillWidth: true
                visible: page.info.fan === true && page.fan.mode !== "auto"
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: "Full speed from " + page.info.full_speed_temp + " °C whatever the setting."
            }

            SwitchRow {
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: page.hasPrime
                text: "Prime core"
                value: page.cpu.prime_core ?? true
                onPicked: on => page.update({cpu: {prime_core: on}})
            }
            SliderRow {
                visible: page.midCount > 1
                text: "Performance cores"
                from: 1
                to: Math.max(2, page.midCount)
                value: page.cpu.mid_cores ?? page.midCount
                valueText: live
                onPicked: v => page.update({cpu: {mid_cores: v}})
            }
            Repeater {
                model: page.clusters

                // steps are the cluster's frequencies, the last one meaning no cap
                SliderRow {
                    required property var modelData
                    readonly property var freqs: modelData.freqs
                    readonly property var cap: page.cpu[modelData.name] ?? null
                    text: (page.clusterLabel[modelData.name] ?? modelData.name) + " max"
                    from: 0
                    to: freqs.length - 1
                    value: cap === null ? to : Math.max(0, freqs.filter(f => f <= cap).length - 1)
                    valueText: live >= to ? "No limit" : page.mhz(freqs[live])
                    onPicked: i => page.update({cpu: {[modelData.name]: i >= to ? null : freqs[i]}})
                }
            }

            QQC2.Button {
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: !page.gameMode ? page.power.customSettings : true
                text: !page.gameMode ? "Use Game Mode's Settings"
                    : page.hasGame && page.power.customSettings ? "Use All-Games Settings for " + page.gameName
                    : "Reset All-Games Settings"
                icon.name: "edit-undo"
                onClicked: page.hasGame && page.power.customSettings ? page.power.setGameOnly(false) : page.power.resetSettings()
            }

            // --- battery, where the charger firmware has a charge limit ---

            Section {
                visible: page.info.charge_limit === true
                text: "Battery"
            }
            SliderRow {
                visible: page.info.charge_limit === true
                text: "Charge limit"
                from: page.info.charge_limit_min ?? 55
                to: 100
                stepSize: 5
                value: page.steam.charge_limit == null || page.steam.charge_limit < 0 ? 100 : page.steam.charge_limit
                valueText: live >= 100 ? "Off" : live + "%"
                onPicked: v => page.power.setSteam("charge_limit", v >= 100 ? -1 : v)
            }
        }

        // --- the app ---

        Section {
            text: "Readings"
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: Kirigami.Units.largeSpacing

            QQC2.Label {
                Layout.fillWidth: true
                text: "Update every"
            }
            Repeater {
                model: [500, 1000, 2000]

                QQC2.Button {
                    required property int modelData
                    text: modelData / 1000 + " s"
                    checkable: false
                    checked: page.interval === modelData
                    onClicked: page.intervalPicked(modelData)
                }
            }
        }
    }

    component Section: Kirigami.Heading {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
        level: 4
    }
}
