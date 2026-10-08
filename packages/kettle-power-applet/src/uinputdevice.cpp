// SPDX-License-Identifier: BSD-3-Clause
#include "uinputdevice.h"

#include <QtGlobal>

#include <cerrno>
#include <cstring>

#include <fcntl.h>
#include <linux/uinput.h>
#include <sys/ioctl.h>
#include <unistd.h>

bool UInputDevice::create(const char *name, int product, const std::vector<int> &keys, const std::vector<int> &rels,
                          bool pointer)
{
    if (m_fd >= 0)
        return true;
    const int fd = ::open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        qWarning("kettle-performance: /dev/uinput: %s", strerror(errno));
        return false;
    }
    bool ok = ioctl(fd, UI_SET_EVBIT, EV_KEY) == 0;
    for (int key : keys)
        ok = ok && ioctl(fd, UI_SET_KEYBIT, key) == 0;
    if (rels.size())
        ok = ok && ioctl(fd, UI_SET_EVBIT, EV_REL) == 0;
    for (int rel : rels)
        ok = ok && ioctl(fd, UI_SET_RELBIT, rel) == 0;
    // a mouse, not a touchpad: libinput then has no tap or palm handling for it
    if (pointer)
        ok = ok && ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER) == 0;

    uinput_setup setup = {};
    setup.id.bustype = BUS_VIRTUAL;
    setup.id.vendor = 0x4b45; // "KE"
    setup.id.product = product;
    setup.id.version = 1;
    strncpy(setup.name, name, UINPUT_MAX_NAME_SIZE - 1);
    ok = ok && ioctl(fd, UI_DEV_SETUP, &setup) == 0 && ioctl(fd, UI_DEV_CREATE) == 0;
    if (!ok) {
        qWarning("kettle-performance: can't make the uinput device %s: %s", name, strerror(errno));
        ::close(fd);
        return false;
    }
    m_fd = fd;
    return true;
}

void UInputDevice::destroy()
{
    if (m_fd < 0)
        return;
    ioctl(m_fd, UI_DEV_DESTROY);
    ::close(m_fd);
    m_fd = -1;
}

void UInputDevice::event(int type, int code, int value)
{
    if (m_fd < 0)
        return;
    input_event ev = {};
    ev.type = type;
    ev.code = code;
    ev.value = value;
    if (write(m_fd, &ev, sizeof(ev)) != sizeof(ev))
        qWarning("kettle-performance: uinput write: %s", strerror(errno));
}

void UInputDevice::sync()
{
    event(EV_SYN, SYN_REPORT, 0);
}
