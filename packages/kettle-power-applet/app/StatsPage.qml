// SPDX-License-Identifier: BSD-3-Clause
// The Stats tab: the game's frame rate and frame times, then a tile per reading.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

QQC2.ScrollView {
    id: page

    required property var power // PowerBackend
    required property var system // SystemStats
    required property var game // GameStats

    readonly property var info: power.info
    readonly property var status: power.status
    readonly property var steam: status.steam ?? ({})
    readonly property var battery: status.battery ?? ({})

    QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
    contentWidth: availableWidth

    function num(v) {
        return v !== undefined && v !== null && !isNaN(v);
    }
    function temp(c) {
        return num(c) ? Math.round(c) + " °C" : "–";
    }
    function pct(v) {
        return num(v) ? Math.round(v * 100) + "%" : "–";
    }
    function gb(bytes) {
        return (bytes / 1073741824).toFixed(1) + " GB";
    }
    function ghz(khz) {
        return khz ? (khz / 1e6).toFixed(1) : "off";
    }
    function duration(hours) {
        const min = Math.round(hours * 60);
        return min >= 60 ? Math.floor(min / 60) + " h " + (min % 60) + " min" : min + " min";
    }

    // clusters running below their top frequency because of a cap (profile, power limit, game)
    readonly property bool cpuCapped: (info.clusters ?? []).some(c => {
        const cap = status.cpu_cap_khz?.[c.name];
        return cap && cap < c.freqs[c.freqs.length - 1];
    })
    readonly property int gpuMax: (info.gpu_mhz ?? []).slice(-1)[0] ?? 0

    ColumnLayout {
        width: page.availableWidth
        spacing: Kirigami.Units.largeSpacing

        // --- the game ---

        Rectangle {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            Layout.bottomMargin: 0
            implicitHeight: gameColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
            Kirigami.Theme.colorSet: Kirigami.Theme.View
            Kirigami.Theme.inherit: false
            color: Kirigami.Theme.backgroundColor
            radius: Kirigami.Units.cornerRadius
            border.width: 1
            border.color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)

            ColumnLayout {
                id: gameColumn
                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: Kirigami.Units.largeSpacing
                }
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true

                    QQC2.Label {
                        Layout.fillWidth: true
                        text: page.game.running ? page.game.name || "Game"
                            : page.game.steamFocused ? "Steam" : "No game running"
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    QQC2.Label {
                        visible: page.game.refresh > 0 && (page.game.running || page.game.steamFocused)
                        text: page.game.refresh + " Hz display"
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: page.game.running || page.game.steamFocused
                    spacing: Kirigami.Units.largeSpacing * 2

                    RowLayout {
                        spacing: Kirigami.Units.smallSpacing
                        QQC2.Label {
                            text: Math.round(page.game.fps)
                            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 2.4
                            font.weight: Font.Bold
                        }
                        QQC2.Label {
                            Layout.alignment: Qt.AlignBaseline
                            text: "fps"
                            opacity: 0.7
                        }
                    }
                    ColumnLayout {
                        spacing: 0
                        QQC2.Label {
                            text: page.game.frameTime.toFixed(1) + " ms"
                        }
                        QQC2.Label {
                            text: page.game.low1 > 0 ? "1% low " + Math.round(page.game.low1) + " fps" : "1% low –"
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                        }
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        visible: page.game.frameGen > 1
                        horizontalAlignment: Text.AlignRight
                        wrapMode: Text.WordWrap
                        text: "Frame generation " + page.game.frameGen + "×\n≈ "
                              + Math.round(page.game.fps / page.game.frameGen) + " fps rendered"
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                    }
                }

                FrameGraph {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 3.5
                    visible: page.game.running || page.game.steamFocused
                    times: page.game.frameTimes
                    refresh: page.game.refresh
                    seconds: page.game.history
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    visible: !page.game.running && !page.game.steamFocused
                    wrapMode: Text.WordWrap
                    text: "The frame rate and frame times show here while a game runs."
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }
            }
        }

        // --- readings ---

        QQC2.Label {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            visible: !page.power.available
            wrapMode: Text.WordWrap
            text: "The power service (kettle-powerd) isn't running: no power, clock or fan readings."
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.largeSpacing
            Layout.topMargin: 0
            columns: page.availableWidth >= Kirigami.Units.gridUnit * 28 ? 4 : 2
            columnSpacing: Kirigami.Units.largeSpacing
            rowSpacing: Kirigami.Units.largeSpacing

            Tile {
                title: "Power"
                value: page.num(page.status.power_w) ? page.status.power_w.toFixed(1) + " W" : "–"
                alert: page.status.tdp_limiting === true
                lines: [
                    page.steam.tdp === undefined ? "" : page.steam.tdp >= (page.info.tdp?.[1] ?? 0) ? "No limit"
                        : "Limit " + page.steam.tdp + " W",
                    page.status.tdp_limiting ? "Holding clocks down" : ""
                ]
            }
            Tile {
                title: "Battery"
                value: page.num(page.battery.capacity) ? page.battery.capacity + "%" : "–"
                lines: {
                    const s = page.battery.status;
                    if (s === "Discharging") {
                        const e = page.system.batteryEnergy;
                        const w = page.status.power_w;
                        return [page.num(e) && w > 0.5 ? page.duration(e / w) + " left" : "On battery"];
                    }
                    return [s === "Charging" ? "Charging" : s === "Full" ? "Full" : s === "Not charging" ? "Plugged in" : s ?? ""];
                }
            }
            Tile {
                title: "CPU"
                value: page.pct(page.system.cpuLoad)
                alert: page.cpuCapped && page.status.tdp_limiting === true
                lines: [
                    Object.values(page.status.cpu_khz ?? {}).map(page.ghz).join(" · ") + " GHz",
                    "Busiest core " + page.pct(page.system.cpuBusiest),
                    page.cpuCapped ? "Max " + Object.values(page.status.cpu_cap_khz ?? {}).map(page.ghz).join(" · ") : ""
                ]
            }
            Tile {
                title: "GPU"
                value: page.num(page.status.gpu_mhz) ? page.status.gpu_mhz + " MHz" : "–"
                alert: page.status.gpu_cap_mhz < page.gpuMax && page.status.tdp_limiting === true
                lines: [
                    page.num(page.status.gpu_load) ? page.pct(page.status.gpu_load) + " busy" : "",
                    page.status.gpu_cap_mhz < page.gpuMax ? "Max " + page.status.gpu_cap_mhz + " MHz" : ""
                ]
            }
            Tile {
                title: "Temperature"
                value: "CPU " + page.temp(page.system.cpuTemp)
                alert: page.num(page.system.cpuTemp) && page.system.cpuTemp >= 85
                lines: [
                    page.num(page.system.gpuTemp) ? "GPU " + page.temp(page.system.gpuTemp) : "",
                    page.num(page.system.batteryTemp) ? "Battery " + page.temp(page.system.batteryTemp) : ""
                ]
            }
            Tile {
                title: "Fan"
                value: page.num(page.status.fan_rpm) ? page.status.fan_rpm + " rpm"
                     : page.num(page.status.fan_pct) ? page.status.fan_pct + "%" : "–"
                lines: [
                    page.num(page.status.fan_rpm) && page.num(page.status.fan_pct) ? page.status.fan_pct + "%" : "",
                    page.status.fan_custom === undefined ? "" : page.status.fan_custom ? "Custom setting" : "Built-in curve",
                    page.num(page.status.temp_c) ? "Sensor " + page.temp(page.status.temp_c) : ""
                ]
            }
            Tile {
                title: "Memory"
                value: page.system.memTotal > 0 ? page.gb(page.system.memUsed) : "–"
                lines: [
                    page.system.memTotal > 0 ? "of " + page.gb(page.system.memTotal) : "",
                    page.system.swapTotal > 0 ? "Swap " + page.gb(page.system.swapUsed) : ""
                ]
            }
            Tile {
                title: "Profile"
                value: page.steam.profile ?? "–"
                lines: [
                    page.steam.gpu_level === "manual" ? "GPU fixed at " + page.steam.gpu_clock + " MHz"
                        : page.steam.gpu_level ? "GPU clock auto" : ""
                ]
            }
        }
    }
}
