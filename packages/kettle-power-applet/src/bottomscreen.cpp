// SPDX-License-Identifier: BSD-3-Clause
#include "bottomscreen.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSaveFile>

#include <algorithm>

namespace
{
// as Device Settings' Screens tab and bottom-brightness have them
constexpr int defaultPercent = 70;
constexpr int minPercent = 2;
// 30: bottom-screen offers it (gamescope 0022)
constexpr int defaultHz = 60;
constexpr int slowHz = 30;
}

BottomScreen::BottomScreen(QObject *parent)
    : QObject(parent)
    , m_path(QDir::homePath() + QStringLiteral("/.config/kettle/bottom-screen.json"))
    , m_dimmedPath(qEnvironmentVariable("XDG_RUNTIME_DIR") + QStringLiteral("/kettle-bottom-dimmed"))
    , m_available(qEnvironmentVariable("KETTLE_BOTTOM_SHELL") == QLatin1String("1")
                  && QFile::exists(QStringLiteral("/sys/class/backlight/bottom-panel")))
{
    if (!m_available)
        return;
    load();
    m_timer.setInterval(2000);
    connect(&m_timer, &QTimer::timeout, this, &BottomScreen::load);
    m_timer.start();
    // the flag comes and goes, so watch its directory (which changes rarely) for it
    m_watcher.addPath(QFileInfo(m_dimmedPath).absolutePath());
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, &BottomScreen::readDimmed);
    readDimmed();
}

void BottomScreen::readDimmed()
{
    const bool dimmed = QFile::exists(m_dimmedPath);
    if (dimmed != m_dimmed) {
        m_dimmed = dimmed;
        Q_EMIT dimmedChanged();
    }
}

void BottomScreen::load()
{
    QFile f(m_path);
    QJsonObject state;
    if (f.open(QIODevice::ReadOnly))
        state = QJsonDocument::fromJson(f.readAll()).object();
    const int percent = std::clamp(state.value(QStringLiteral("brightness")).toInt(defaultPercent), minPercent, 100);
    if (percent != m_brightness) {
        m_brightness = percent;
        Q_EMIT brightnessChanged();
    }
    const int hz = state.value(QStringLiteral("refresh_hz")).toInt(defaultHz) == slowHz ? slowHz : defaultHz;
    if (hz != m_refreshHz) {
        m_refreshHz = hz;
        Q_EMIT refreshHzChanged();
    }
}

void BottomScreen::save(const QString &key, int value)
{
    // the file's other settings ("enabled") stay as they are
    QJsonObject state;
    {
        QFile f(m_path);
        if (f.open(QIODevice::ReadOnly))
            state = QJsonDocument::fromJson(f.readAll()).object();
    }
    state.insert(key, value);
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    QSaveFile out(m_path);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QJsonDocument(state).toJson(QJsonDocument::Compact));
        if (!out.commit())
            qWarning("kettle-power: %s: %s", qPrintable(m_path), qPrintable(out.errorString()));
    }
}

void BottomScreen::setBrightness(int percent)
{
    percent = std::clamp(percent, minPercent, 100);
    if (!m_available || percent == m_brightness)
        return;
    save(QStringLiteral("brightness"), percent);
    m_brightness = percent;
    Q_EMIT brightnessChanged();
}

void BottomScreen::setRefreshHz(int hz)
{
    hz = hz == slowHz ? slowHz : defaultHz;
    if (!m_available || hz == m_refreshHz)
        return;
    save(QStringLiteral("refresh_hz"), hz);
    m_refreshHz = hz;
    Q_EMIT refreshHzChanged();
    // live, on the bottom screen's gamescope (bottom-shell names it), as Device Settings does: a
    // fixed rate (gamescope 0023), which switches at once
    QFile name(qEnvironmentVariable("XDG_RUNTIME_DIR") + QStringLiteral("/kettle-bottom-gamescope"));
    if (!name.open(QIODevice::ReadOnly))
        return;
    const QString display = QString::fromUtf8(name.readAll()).trimmed();
    if (display.isEmpty())
        return;
    auto *p = new QProcess(this);
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert(QStringLiteral("GAMESCOPE_WAYLAND_DISPLAY"), display);
    p->setProcessEnvironment(env);
    connect(p, &QProcess::finished, p, &QObject::deleteLater);
    connect(p, &QProcess::errorOccurred, p, &QObject::deleteLater);
    p->start(QStringLiteral("gamescopectl"), {QStringLiteral("refresh_hz"), QString::number(hz)});
}
