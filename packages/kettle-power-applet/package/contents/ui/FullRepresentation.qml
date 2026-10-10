// SPDX-License-Identifier: BSD-3-Clause
// The popup: a readout, Steam's values (profile, power limit, GPU clock) and Desktop Mode's fan
// and CPU settings, the same controls as Quick Access > Performance and Game Settings.
import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: full

    required property var power // PowerBackend

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

    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.preferredWidth: Kirigami.Units.gridUnit * 22
    Layout.preferredHeight: Kirigami.Units.gridUnit * 30

    function mhz(khz) {
        return khz ? Math.round(khz / 1000) + " MHz" : "off";
    }

    // Desktop Mode's fan and CPU settings with a change in fan or cpu
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

    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: !full.ready
        iconName: "speedometer"
        text: full.power.available ? "Reading the power settings…" : "The power service (kettle-powerd) isn't running"
    }

    PlasmaComponents3.ScrollView {
        id: scroll
        anchors.fill: parent
        visible: full.ready
        PlasmaComponents3.ScrollBar.horizontal.policy: PlasmaComponents3.ScrollBar.AlwaysOff

        ColumnLayout {
            width: scroll.availableWidth
            spacing: Kirigami.Units.smallSpacing

            // --- now ---

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: 0

                PlasmaComponents3.Label { text: "Power draw"; opacity: 0.7 }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: full.status.power_w == null ? "–"
                        : full.status.power_w.toFixed(1) + " W" + (full.status.tdp_limiting ? " (limiting)" : "")
                }
                PlasmaComponents3.Label { text: "Temperature"; opacity: 0.7 }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: full.status.temp_c == null ? "–" : Math.round(full.status.temp_c) + " °C"
                }
                PlasmaComponents3.Label { text: "Fan"; opacity: 0.7; visible: full.status.fan_rpm != null }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    visible: full.status.fan_rpm != null
                    text: full.status.fan_rpm + " RPM (" + full.status.fan_pct + "%)"
                }
                PlasmaComponents3.Label { text: "CPU"; opacity: 0.7 }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: Object.values(full.status.cpu_khz ?? {}).map(v => v ? Math.round(v / 1000) : "–").join(" / ") + " MHz"
                }
                PlasmaComponents3.Label { text: "GPU"; opacity: 0.7 }
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: full.status.gpu_mhz + " MHz"
                        + (full.status.gpu_load != null ? ", " + Math.round(full.status.gpu_load * 100) + "% busy" : "")
                }
            }

            // --- Steam's values ---

            Kirigami.Heading {
                Layout.topMargin: Kirigami.Units.largeSpacing
                level: 4
                text: "Performance profile"
            }
            RowLayout {
                Layout.fillWidth: true

                Repeater {
                    // slowest first, as in Plasma's own power profiles
                    model: (full.info.profiles ?? []).slice().reverse()

                    PlasmaComponents3.Button {
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1 // same width each
                        text: modelData
                        checkable: false
                        checked: full.steam.profile === modelData
                        onClicked: full.power.setSteam("profile", modelData)
                    }
                }
            }

            SliderRow {
                Layout.topMargin: Kirigami.Units.smallSpacing
                text: "Power limit"
                from: full.info.tdp?.[0] ?? 0
                to: full.info.tdp?.[1] ?? 1
                value: full.steam.tdp ?? to
                valueText: live >= to ? "No limit" : live + " W"
                onPicked: v => full.power.setSteam("tdp", v)
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: "The whole device's draw, screen included."
            }

            SwitchRow {
                Layout.topMargin: Kirigami.Units.smallSpacing
                text: "Fixed GPU clock"
                value: full.steam.gpu_level === "manual"
                onPicked: on => full.power.setSteam("gpu_level", on ? "manual" : "auto")
            }
            SliderRow {
                visible: full.steam.gpu_level === "manual" && full.gpuSteps.length > 1
                text: "GPU clock"
                from: 0
                to: full.gpuSteps.length - 1
                value: Math.max(0, full.gpuSteps.filter(f => f <= full.steam.gpu_clock).length - 1)
                valueText: full.gpuSteps[live] + " MHz"
                onPicked: i => full.power.setSteam("gpu_clock", full.gpuSteps[i])
            }

            // --- Desktop Mode's fan and CPU settings ---

            Kirigami.Heading {
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: full.info.fan === true
                level: 4
                text: "Fan"
            }
            PlasmaComponents3.ComboBox {
                id: fanMode
                readonly property var modes: ["auto", "curve", "fixed"]
                Layout.fillWidth: true
                visible: full.info.fan === true
                model: ["Automatic (built-in curve)", "Custom curve", "Fixed speed"]
                currentIndex: modes.indexOf(full.fan.mode)
                onActivated: index => {
                    full.update({fan: {mode: modes[index]}});
                    currentIndex = Qt.binding(() => modes.indexOf(full.fan.mode));
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: full.info.fan === true && full.fan.mode !== "auto" && full.steam.fan_control === 0

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "Fan control is off in Steam's settings, so the built-in curve runs."
                }
                PlasmaComponents3.Button {
                    text: "Turn On"
                    onClicked: full.power.setSteam("fan_control", 1)
                }
            }
            SliderRow {
                visible: full.info.fan === true && full.fan.mode === "fixed"
                text: "Fan speed"
                from: 0
                to: 100
                stepSize: 5
                value: full.fan.fixed ?? 50
                valueText: live + "%"
                onPicked: v => full.update({fan: {fixed: v}})
            }
            Repeater {
                model: full.info.fan === true && full.fan.mode === "curve" ? full.fan.curve : []

                SliderRow {
                    required property var modelData
                    required property int index
                    text: "At " + modelData[0] + " °C"
                    from: 0
                    to: 100
                    stepSize: 5
                    value: modelData[1]
                    valueText: live + "%"
                    onPicked: v => full.update({fan: {curve: full.setPoint(full.fan.curve, index, v)}})
                }
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: full.info.fan === true && full.fan.mode !== "auto"
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: "Full speed from " + full.info.full_speed_temp + " °C whatever the setting."
            }

            Kirigami.Heading {
                Layout.topMargin: Kirigami.Units.largeSpacing
                level: 4
                text: "CPU"
            }
            SwitchRow {
                visible: full.hasPrime
                text: "Prime core"
                value: full.cpu.prime_core ?? true
                onPicked: on => full.update({cpu: {prime_core: on}})
            }
            SliderRow {
                visible: full.midCount > 1
                text: "Performance cores"
                from: 1
                to: Math.max(2, full.midCount)
                value: full.cpu.mid_cores ?? full.midCount
                valueText: live
                onPicked: v => full.update({cpu: {mid_cores: v}})
            }
            Repeater {
                model: full.clusters

                // steps are the cluster's frequencies, the last one meaning no cap
                SliderRow {
                    required property var modelData
                    readonly property var freqs: modelData.freqs
                    readonly property var cap: full.cpu[modelData.name] ?? null
                    text: (full.clusterLabel[modelData.name] ?? modelData.name) + " max"
                    from: 0
                    to: freqs.length - 1
                    value: cap === null ? to : Math.max(0, freqs.filter(f => f <= cap).length - 1)
                    valueText: live >= to ? "No limit" : full.mhz(freqs[live])
                    onPicked: i => full.update({cpu: {[modelData.name]: i >= to ? null : freqs[i]}})
                }
            }

            PlasmaComponents3.Label {
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                text: full.power.customSettings
                    ? "Desktop Mode has its own fan and CPU settings. Game Mode keeps its own."
                    : "Fan and CPU: Game Mode's settings for all games, until you change one here."
            }
            PlasmaComponents3.Button {
                visible: full.power.customSettings
                text: "Use Game Mode's Settings"
                icon.name: "edit-undo"
                onClicked: full.power.resetSettings()
            }

            // --- battery, where the charger firmware has a charge limit ---

            Kirigami.Heading {
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: full.info.charge_limit === true
                level: 4
                text: "Battery"
            }
            SliderRow {
                visible: full.info.charge_limit === true
                text: "Charge limit"
                from: full.info.charge_limit_min ?? 55
                to: 100
                stepSize: 5
                value: full.steam.charge_limit == null || full.steam.charge_limit < 0 ? 100 : full.steam.charge_limit
                valueText: live >= 100 ? "Off" : live + "%"
                onPicked: v => full.power.setSteam("charge_limit", v >= 100 ? -1 : v)
            }
        }
    }
}
