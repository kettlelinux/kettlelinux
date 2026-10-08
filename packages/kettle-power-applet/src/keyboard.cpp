// SPDX-License-Identifier: BSD-3-Clause
#include "keyboard.h"

#include <linux/input.h>

namespace
{
// a PC keyboard's keys: Esc to F12, the arrows, Insert, Delete, Home, End, Page Up/Down and Meta
std::vector<int> keys()
{
    std::vector<int> all;
    for (int key = KEY_ESC; key <= KEY_F12; ++key)
        all.push_back(key);
    for (int key = KEY_HOME; key <= KEY_DELETE; ++key)
        all.push_back(key);
    all.push_back(KEY_LEFTMETA);
    return all;
}
}

Keyboard::Keyboard(QObject *parent)
    : QObject(parent)
{
}

void Keyboard::setActive(bool active)
{
    if (active == m_active)
        return;
    m_active = active;
    const bool had = m_device.exists();
    if (active)
        m_device.create("Kettle Keyboard", 0x0002, keys(), {}, false);
    else
        m_device.destroy();
    Q_EMIT activeChanged();
    if (m_device.exists() != had)
        Q_EMIT availableChanged();
}

void Keyboard::press(int key)
{
    m_device.event(EV_KEY, key, 1);
    m_device.sync();
}

void Keyboard::release(int key)
{
    m_device.event(EV_KEY, key, 0);
    m_device.sync();
}
