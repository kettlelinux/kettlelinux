// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <vector>

// A uinput device for Game Mode's gamescope to read (the Trackpad and Keyboard tabs). The
// session's user may make one: Steam's udev rules give the seat's user /dev/uinput (uaccess), as
// desktop-controller uses it.
class UInputDevice
{
public:
    ~UInputDevice() { destroy(); }

    // keys and relative axes it has (EV_KEY and EV_REL codes); false (and a warning) if it can't
    bool create(const char *name, int product, const std::vector<int> &keys, const std::vector<int> &rels,
                bool pointer);
    // keys it had down go up with it
    void destroy();
    bool exists() const { return m_fd >= 0; }

    void event(int type, int code, int value);
    void sync();

private:
    int m_fd = -1;
};
