// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <qqmlregistration.h>

#include "uinputdevice.h"

// A mouse for Game Mode, from the Thor's bottom screen: a uinput device, "Kettle Trackpad".
// The bottom screen's gamescope only gets that screen's touches; any pointer goes to Game Mode's
// gamescope, so this one moves the top screen's pointer, over Steam and the running game.
// It exists while `active` (the Trackpad tab is open), so nothing else sees a mouse otherwise.
class Trackpad : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    // the device is made (/dev/uinput opened)
    Q_PROPERTY(bool available READ available NOTIFY availableChanged)

public:
    enum Button { Left, Right, Middle };
    Q_ENUM(Button)

    explicit Trackpad(QObject *parent = nullptr);

    bool active() const { return m_active; }
    void setActive(bool active);
    bool available() const { return m_device.exists(); }

    // pointer motion, in top-screen pixels (fractions carry over to the next move)
    Q_INVOKABLE void move(qreal dx, qreal dy);
    // wheel motion, in detents (fractions carry over); positive is up and right
    Q_INVOKABLE void scroll(qreal dx, qreal dy);
    Q_INVOKABLE void press(Trackpad::Button button);
    Q_INVOKABLE void release(Trackpad::Button button);
    Q_INVOKABLE void click(Trackpad::Button button);

Q_SIGNALS:
    void activeChanged();
    void availableChanged();

private:
    UInputDevice m_device;
    bool m_active = false;
    qreal m_restX = 0, m_restY = 0;
    qreal m_wheelX = 0, m_wheelY = 0;
};
