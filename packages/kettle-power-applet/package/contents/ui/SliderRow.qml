// SPDX-License-Identifier: BSD-3-Clause
// A labelled slider that follows `value` except while it's held, and reports a new value once,
// when it's let go (kettle-powerd changes clocks at once: no writes on every step of a drag).
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: row

    property alias text: label.text
    property string valueText
    property real value
    property alias from: slider.from
    property alias to: slider.to
    property alias stepSize: slider.stepSize
    readonly property alias live: slider.value

    signal picked(real value)

    Layout.fillWidth: true
    spacing: 0

    RowLayout {
        Layout.fillWidth: true

        PlasmaComponents3.Label {
            id: label
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        PlasmaComponents3.Label {
            text: row.valueText
            opacity: 0.7
        }
    }

    PlasmaComponents3.Slider {
        id: slider
        Layout.fillWidth: true
        stepSize: 1
        snapMode: QQC2.Slider.SnapAlways
        // pressed covers the keyboard too; moved without it is the mouse wheel
        onPressedChanged: if (!pressed && value !== row.value) row.picked(value)
        onMoved: if (!pressed) row.picked(value)

        Binding on value {
            value: row.value
            when: !slider.pressed
            restoreMode: Binding.RestoreNone
        }
    }
}
