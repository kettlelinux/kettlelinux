// SPDX-License-Identifier: BSD-3-Clause
#include "trackpad.h"

#include <cmath>

#include <linux/input.h>

namespace
{
int code(Trackpad::Button button)
{
    switch (button) {
    case Trackpad::Right:
        return BTN_RIGHT;
    case Trackpad::Middle:
        return BTN_MIDDLE;
    default:
        return BTN_LEFT;
    }
}

// the whole part of value + rest, keeping the fraction in rest
int whole(qreal value, qreal &rest)
{
    rest += value;
    const qreal n = std::trunc(rest);
    rest -= n;
    return int(n);
}
}

Trackpad::Trackpad(QObject *parent)
    : QObject(parent)
{
}

void Trackpad::setActive(bool active)
{
    if (active == m_active)
        return;
    m_active = active;
    const bool had = m_device.exists();
    if (active) {
        m_device.create("Kettle Trackpad", 0x0001, {BTN_LEFT, BTN_RIGHT, BTN_MIDDLE},
                        {REL_X, REL_Y, REL_WHEEL, REL_HWHEEL}, true);
        m_restX = m_restY = m_wheelX = m_wheelY = 0;
    } else {
        m_device.destroy();
    }
    Q_EMIT activeChanged();
    if (m_device.exists() != had)
        Q_EMIT availableChanged();
}

void Trackpad::move(qreal dx, qreal dy)
{
    if (!m_device.exists())
        return;
    const int x = whole(dx, m_restX);
    const int y = whole(dy, m_restY);
    if (!x && !y)
        return;
    if (x)
        m_device.event(EV_REL, REL_X, x);
    if (y)
        m_device.event(EV_REL, REL_Y, y);
    m_device.sync();
}

void Trackpad::scroll(qreal dx, qreal dy)
{
    if (!m_device.exists())
        return;
    const int x = whole(dx, m_wheelX);
    const int y = whole(dy, m_wheelY);
    if (!x && !y)
        return;
    if (y)
        m_device.event(EV_REL, REL_WHEEL, y);
    if (x)
        m_device.event(EV_REL, REL_HWHEEL, x);
    m_device.sync();
}

void Trackpad::press(Trackpad::Button button)
{
    m_device.event(EV_KEY, code(button), 1);
    m_device.sync();
}

void Trackpad::release(Trackpad::Button button)
{
    m_device.event(EV_KEY, code(button), 0);
    m_device.sync();
}

void Trackpad::click(Trackpad::Button button)
{
    press(button);
    release(button);
}
