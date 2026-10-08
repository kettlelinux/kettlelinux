// SPDX-License-Identifier: BSD-3-Clause
// The Keyboard tab (Game Mode): a US PC keyboard on the bottom screen, typing into Steam and the
// running game on the top one. A key is down as long as it's touched (held for games, repeating
// in text); Shift, Ctrl and Alt latch when tapped and go up after the next key, or tap them again.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

Item {
    id: page

    required property var keyboard // Keyboard

    // Linux key codes (linux/input-event-codes.h) of the latching modifiers
    readonly property var modifiers: [29, 42, 54, 56] // Left Ctrl, Left Shift, Right Shift, Left Alt
    // the modifiers latched now, code -> true
    property var latched: ({})
    property bool capsLock: false
    readonly property bool shifted: !!(latched[42] || latched[54])

    // each row is 15 units wide; w is a key's width in units (1 when left out)
    readonly property var rows: [
        [{l: "Esc", c: 1, w: 1.5}, {l: "F1", c: 59}, {l: "F2", c: 60}, {l: "F3", c: 61}, {l: "F4", c: 62},
         {l: "F5", c: 63}, {l: "F6", c: 64}, {l: "F7", c: 65}, {l: "F8", c: 66}, {l: "F9", c: 67},
         {l: "F10", c: 68}, {l: "F11", c: 87}, {l: "F12", c: 88}, {l: "Del", c: 111, w: 1.5}],
        [{l: "`", s: "~", c: 41}, {l: "1", s: "!", c: 2}, {l: "2", s: "@", c: 3}, {l: "3", s: "#", c: 4},
         {l: "4", s: "$", c: 5}, {l: "5", s: "%", c: 6}, {l: "6", s: "^", c: 7}, {l: "7", s: "&", c: 8},
         {l: "8", s: "*", c: 9}, {l: "9", s: "(", c: 10}, {l: "0", s: ")", c: 11}, {l: "-", s: "_", c: 12},
         {l: "=", s: "+", c: 13}, {l: "⌫", c: 14, w: 2}],
        [{l: "Tab", c: 15, w: 1.5}, {l: "q", c: 16}, {l: "w", c: 17}, {l: "e", c: 18}, {l: "r", c: 19},
         {l: "t", c: 20}, {l: "y", c: 21}, {l: "u", c: 22}, {l: "i", c: 23}, {l: "o", c: 24}, {l: "p", c: 25},
         {l: "[", s: "{", c: 26}, {l: "]", s: "}", c: 27}, {l: "\\", s: "|", c: 43, w: 1.5}],
        [{l: "Caps", c: 58, w: 1.75}, {l: "a", c: 30}, {l: "s", c: 31}, {l: "d", c: 32}, {l: "f", c: 33},
         {l: "g", c: 34}, {l: "h", c: 35}, {l: "j", c: 36}, {l: "k", c: 37}, {l: "l", c: 38},
         {l: ";", s: ":", c: 39}, {l: "'", s: "\"", c: 40}, {l: "Enter", c: 28, w: 2.25}],
        [{l: "Shift", c: 42, w: 2.25}, {l: "z", c: 44}, {l: "x", c: 45}, {l: "c", c: 46}, {l: "v", c: 47},
         {l: "b", c: 48}, {l: "n", c: 49}, {l: "m", c: 50}, {l: ",", s: "<", c: 51}, {l: ".", s: ">", c: 52},
         {l: "/", s: "?", c: 53}, {l: "Shift", c: 54, w: 2.75}],
        [{l: "Ctrl", c: 29, w: 1.5}, {l: "Alt", c: 56, w: 1.5}, {l: "Space", c: 57, w: 8},
         {l: "←", c: 105}, {l: "↑", c: 103}, {l: "↓", c: 108}, {l: "→", c: 106}]
    ]

    function label(key) {
        if (key.s !== undefined)
            return shifted ? key.s : key.l;
        // letters: Shift and Caps Lock make them capitals, one undoing the other
        if (key.l.length === 1)
            return shifted !== capsLock ? key.l.toUpperCase() : key.l;
        return key.l;
    }

    function setLatched(code, on) {
        const next = Object.assign({}, latched);
        if (on)
            next[code] = true;
        else
            delete next[code];
        latched = next;
        on ? keyboard.press(code) : keyboard.release(code);
    }

    function releaseLatched() {
        for (const code of Object.keys(latched))
            keyboard.release(Number(code));
        latched = {};
    }

    // the device went (the tab closed): it let go of every key, so the latches go too
    Connections {
        target: page.keyboard
        function onAvailableChanged() {
            page.latched = {};
        }
    }

    QQC2.Label {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        visible: !page.keyboard.available
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        text: "The keyboard needs /dev/uinput, which this session can't open."
    }

    Column {
        id: keys

        readonly property real gap: Kirigami.Units.smallSpacing / 2
        readonly property real unit: width / 15
        readonly property real keyHeight: (height - gap * (page.rows.length - 1)) / page.rows.length

        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        visible: page.keyboard.available
        spacing: gap

        Repeater {
            model: page.rows

            Row {
                id: row
                required property var modelData
                spacing: 0

                Repeater {
                    model: row.modelData

                    Item {
                        id: cell
                        required property var modelData
                        readonly property bool modifier: page.modifiers.includes(modelData.c)

                        width: (modelData.w ?? 1) * keys.unit
                        height: keys.keyHeight

                        QQC2.Button {
                            anchors.fill: parent
                            anchors.margins: keys.gap / 2
                            padding: 0
                            focusPolicy: Qt.NoFocus
                            text: page.label(cell.modelData)
                            font.pixelSize: Math.min(height * 0.4, Kirigami.Theme.defaultFont.pixelSize)
                            // shrunk to fit, not elided: the style's label made "F10" dots
                            contentItem: QQC2.Label {
                                text: parent.text
                                font: parent.font
                                color: parent.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                fontSizeMode: Text.HorizontalFit
                                minimumPixelSize: 6
                                leftPadding: 1
                                rightPadding: 1
                            }
                            checkable: false
                            checked: cell.modifier ? !!page.latched[cell.modelData.c]
                                     : cell.modelData.c === 58 && page.capsLock
                            highlighted: checked

                            onPressedChanged: {
                                const code = cell.modelData.c;
                                if (cell.modifier) {
                                    if (pressed)
                                        page.setLatched(code, !page.latched[code]);
                                } else if (pressed) {
                                    page.keyboard.press(code);
                                    if (code === 58)
                                        page.capsLock = !page.capsLock;
                                } else {
                                    page.keyboard.release(code);
                                    page.releaseLatched();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
