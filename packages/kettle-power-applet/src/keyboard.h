// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <qqmlregistration.h>

#include "uinputdevice.h"

// A keyboard for Game Mode, from the Thor's bottom screen: a uinput device, "Kettle Keyboard",
// which Game Mode's gamescope reads (as with Trackpad), typing into Steam and the running game.
// It exists while `active` (the Keyboard tab is open). Keys are Linux key codes (linux/input-event-codes.h).
class Keyboard : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    // the device is made (/dev/uinput opened)
    Q_PROPERTY(bool available READ available NOTIFY availableChanged)

public:
    explicit Keyboard(QObject *parent = nullptr);

    bool active() const { return m_active; }
    void setActive(bool active);
    bool available() const { return m_device.exists(); }

    Q_INVOKABLE void press(int key);
    Q_INVOKABLE void release(int key);

Q_SIGNALS:
    void activeChanged();
    void availableChanged();

private:
    UInputDevice m_device;
    bool m_active = false;
};
