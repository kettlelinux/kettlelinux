// SPDX-License-Identifier: BSD-3-Clause
// The Trackpad tab (Game Mode): the bottom screen as a mouse for the top one, over Steam and the
// running game. One finger moves the pointer, a tap clicks (two fingers: a right click), two
// fingers scroll; the buttons along the bottom are held down as long as they're touched, so one
// thumb can hold Left while the other drags.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.kettle.private.power

ColumnLayout {
    id: page

    required property var trackpad // Trackpad
    // top-screen pixels per bottom-screen (logical) pixel moved (Settings > Trackpad speed);
    // libinput accelerates on top of it
    required property real speed
    // bottom-screen pixels per wheel detent, two-finger scrolling
    readonly property real scrollStep: 24
    // a touch shorter and stiller than these is a tap
    readonly property int tapMs: 220
    readonly property real tapSlop: 10

    spacing: Kirigami.Units.smallSpacing

    QQC2.Label {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !page.trackpad.available
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        text: "The trackpad needs /dev/uinput, which this session can't open."
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.margins: Kirigami.Units.largeSpacing
        Layout.bottomMargin: 0
        visible: page.trackpad.available
        radius: Kirigami.Units.cornerRadius * 2
        color: Kirigami.Theme.alternateBackgroundColor
        border.color: area.pressedCount > 0 ? Kirigami.Theme.highlightColor : Kirigami.Theme.disabledTextColor
        border.width: 1

        Kirigami.Icon {
            anchors.centerIn: parent
            width: Kirigami.Units.iconSizes.huge
            height: width
            source: "input-touchpad"
            opacity: 0.15
        }

        MultiPointTouchArea {
            id: area

            // the gesture so far: when it began, the most fingers it had, how far it went
            property int pressedCount: 0
            property double startTime: 0
            property int fingers: 0
            property real travel: 0

            anchors.fill: parent
            maximumTouchPoints: 2
            touchPoints: [
                TouchPoint { id: p1 },
                TouchPoint { id: p2 }
            ]

            function count() {
                return (p1.pressed ? 1 : 0) + (p2.pressed ? 1 : 0);
            }

            onPressed: {
                if (pressedCount === 0) {
                    startTime = Date.now();
                    fingers = 0;
                    travel = 0;
                }
                pressedCount = count();
                fingers = Math.max(fingers, pressedCount);
            }
            onUpdated: touches => {
                let dx = 0, dy = 0;
                for (const t of touches) {
                    dx += t.x - t.previousX;
                    dy += t.y - t.previousY;
                }
                dx /= touches.length;
                dy /= touches.length;
                travel += Math.hypot(dx, dy);
                if (count() >= 2)
                    // natural scrolling, as on the touchscreen: the page follows the fingers
                    page.trackpad.scroll(-dx / page.scrollStep, dy / page.scrollStep);
                else
                    page.trackpad.move(dx * page.speed, dy * page.speed);
            }
            onReleased: {
                pressedCount = count();
                if (pressedCount > 0)
                    return;
                if (Date.now() - startTime < page.tapMs && travel < page.tapSlop)
                    page.trackpad.click(fingers >= 2 ? Trackpad.Right : Trackpad.Left);
            }
            onCanceled: pressedCount = count()
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.largeSpacing
        Layout.topMargin: 0
        // a strip: the buttons fill it, which would otherwise make the row share the height
        Layout.fillHeight: false
        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
        visible: page.trackpad.available
        spacing: Kirigami.Units.smallSpacing

        component MouseButton: QQC2.Button {
            required property int button

            Layout.fillWidth: true
            Layout.fillHeight: true
            onPressedChanged: pressed ? page.trackpad.press(button) : page.trackpad.release(button)
        }

        MouseButton {
            button: Trackpad.Left
            text: "Left"
        }
        MouseButton {
            button: Trackpad.Right
            text: "Right"
        }
    }
}
