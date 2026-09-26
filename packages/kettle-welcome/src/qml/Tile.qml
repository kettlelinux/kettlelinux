// SPDX-License-Identifier: BSD-3-Clause
// A card-like button: icon, title and a line or two of explanation.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

QQC2.ItemDelegate {
    id: tile

    property string iconName
    property string title
    property string subtitle
    // a small note under the subtitle, e.g. "Opens System Settings"
    property string hint

    Layout.fillWidth: true
    Layout.fillHeight: true  // tiles in a row match the tallest
    Layout.preferredWidth: Kirigami.Units.gridUnit * 18
    Layout.maximumWidth: parent && parent.cellWidth > 0 ? parent.cellWidth : Number.POSITIVE_INFINITY
    padding: Kirigami.Units.largeSpacing
    hoverEnabled: true

    Accessible.name: title
    Accessible.description: subtitle

    background: Kirigami.ShadowedRectangle {
        Kirigami.Theme.colorSet: Kirigami.Theme.View
        Kirigami.Theme.inherit: false
        radius: Kirigami.Units.largeSpacing
        readonly property color text: Kirigami.Theme.textColor
        color: tile.down ? Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.highlightColor, 0.3)
             : tile.hovered || tile.visualFocus ? Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.highlightColor, 0.12)
             : Kirigami.Theme.backgroundColor
        border.width: 1
        border.color: tile.hovered || tile.visualFocus ? Kirigami.Theme.highlightColor : Qt.rgba(text.r, text.g, text.b, 0.15)
        shadow.size: Kirigami.Units.smallSpacing
        shadow.color: Qt.rgba(0, 0, 0, 0.12)
        shadow.yOffset: 1
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            Layout.alignment: Qt.AlignTop
            implicitWidth: Kirigami.Units.iconSizes.large
            implicitHeight: implicitWidth
            source: tile.iconName
            fallback: "applications-other"
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing / 2

            QQC2.Label {
                Layout.fillWidth: true
                text: tile.title
                font.bold: true
                wrapMode: Text.Wrap
            }
            QQC2.Label {
                Layout.fillWidth: true
                text: tile.subtitle
                visible: text.length > 0
                wrapMode: Text.Wrap
                opacity: 0.75
            }
            QQC2.Label {
                Layout.fillWidth: true
                text: tile.hint
                visible: text.length > 0
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
                color: Kirigami.Theme.linkColor
            }
        }
    }
}
