// SPDX-License-Identifier: BSD-3-Clause
// One reading on the Stats tab: a title, the value, and a line or two under it.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

Rectangle {
    id: tile

    property string title
    property string value
    // lines under the value; empty ones are left out
    property var lines: []
    // shown in the warning colour: something is holding performance back
    property bool alert: false

    Layout.fillWidth: true
    Layout.preferredWidth: 1 // tiles in a row share it equally
    Layout.alignment: Qt.AlignTop
    implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing * 2

    Kirigami.Theme.colorSet: Kirigami.Theme.View
    Kirigami.Theme.inherit: false
    color: Kirigami.Theme.backgroundColor
    radius: Kirigami.Units.cornerRadius
    border.width: 1
    border.color: tile.alert ? Kirigami.Theme.neutralTextColor
                             : Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)

    ColumnLayout {
        id: column
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            margins: Kirigami.Units.largeSpacing
        }
        spacing: 0

        QQC2.Label {
            Layout.fillWidth: true
            text: tile.title
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            elide: Text.ElideRight
        }
        QQC2.Label {
            Layout.fillWidth: true
            text: tile.value
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.4
            font.weight: Font.DemiBold
            color: tile.alert ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor
            elide: Text.ElideRight
        }
        Repeater {
            model: tile.lines.filter(l => l)

            QQC2.Label {
                required property string modelData
                Layout.fillWidth: true
                text: modelData
                font: Kirigami.Theme.smallFont
                opacity: 0.8
                elide: Text.ElideRight
            }
        }
    }
}
