// SPDX-License-Identifier: BSD-3-Clause
#include "bottomscreen.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>

#include <algorithm>

namespace
{
// as Device Settings' Screens tab and bottom-brightness have them
constexpr int defaultPercent = 70;
constexpr int minPercent = 2;
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
    int percent = defaultPercent;
    if (f.open(QIODevice::ReadOnly))
        percent = QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("brightness")).toInt(defaultPercent);
    percent = std::clamp(percent, minPercent, 100);
    if (percent != m_brightness) {
        m_brightness = percent;
        Q_EMIT brightnessChanged();
    }
}

void BottomScreen::setBrightness(int percent)
{
    percent = std::clamp(percent, minPercent, 100);
    if (!m_available || percent == m_brightness)
        return;
    // the file's other settings ("enabled") stay as they are
    QJsonObject state;
    {
        QFile f(m_path);
        if (f.open(QIODevice::ReadOnly))
            state = QJsonDocument::fromJson(f.readAll()).object();
    }
    state.insert(QStringLiteral("brightness"), percent);
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    QSaveFile out(m_path);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QJsonDocument(state).toJson(QJsonDocument::Compact));
        if (!out.commit())
            qWarning("kettle-power: %s: %s", qPrintable(m_path), qPrintable(out.errorString()));
    }
    m_brightness = percent;
    Q_EMIT brightnessChanged();
}
