// SPDX-License-Identifier: BSD-3-Clause
// A switch that shows `value` and reports a flip, keeping its binding to `value` afterwards.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

QQC2.Switch {
    id: control

    property bool value

    signal picked(bool on)

    Layout.fillWidth: true
    checked: value
    onToggled: {
        picked(checked);
        checked = Qt.binding(() => control.value);
    }
}
