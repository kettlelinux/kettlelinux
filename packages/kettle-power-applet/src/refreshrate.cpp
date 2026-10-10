// SPDX-License-Identifier: BSD-3-Clause
#include "refreshrate.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QRegularExpression>
#include <QSaveFile>

#include <algorithm>

namespace
{
const QString ratesFile = QStringLiteral("/usr/lib/kettle/refresh-rates");
// what gamescope-session starts at until a rate is picked (gamescope_refresh_hz)
const QString gamescopeConf = QStringLiteral("/usr/lib/kettle/gamescope.conf");
constexpr int autoHz = 0;

QString readAll(const QString &path)
{
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? QString::fromUtf8(f.readAll()) : QString();
}

int firstNumber(const QString &text, const QString &pattern)
{
    const auto m = QRegularExpression(pattern, QRegularExpression::MultilineOption).match(text);
    return m.hasMatch() ? m.captured(1).toInt() : -1;
}
}

RefreshRate::RefreshRate(QObject *parent)
    : QObject(parent)
    , m_confPath(QDir::homePath() + QStringLiteral("/.config/kettle/refresh-rate.conf"))
    , m_gamesPath(QDir::homePath() + QStringLiteral("/homebrew/settings/kettle-power/refresh-rates.json"))
{
    QList<int> have;
    for (const QString &r : readAll(ratesFile).split(QRegularExpression(QStringLiteral("\\s+")), Qt::SkipEmptyParts))
        if (r.toInt() > 0)
            have.append(r.toInt());
    std::sort(have.begin(), have.end());
    for (int r : have)
        m_rates.append(r);
    // the device's own, not the highest: the Portal lists 165 Hz, but starts at 120
    const int start = firstNumber(readAll(gamescopeConf), QStringLiteral("^export gamescope_refresh_hz=(\\d+)"));
    m_default = have.contains(start) ? start : have.isEmpty() ? autoHz : have.last();
    m_allGames = m_default;
    m_available = qEnvironmentVariable("KETTLE_BOTTOM_SHELL") == QLatin1String("1") && have.size() >= 2;
    if (!m_available)
        return;
    load();
    // the plugins change the same files
    m_timer.setInterval(2000);
    connect(&m_timer, &QTimer::timeout, this, &RefreshRate::load);
    m_timer.start();
}

bool RefreshRate::valid(int hz) const
{
    return hz == autoHz || m_rates.contains(hz);
}

void RefreshRate::load()
{
    int all = firstNumber(readAll(m_confPath), QStringLiteral("gamescope_refresh_hz=(\\d+)"));
    if (!valid(all))
        all = m_default;
    QVariantMap games;
    const QJsonObject saved = QJsonDocument::fromJson(readAll(m_gamesPath).toUtf8()).object();
    for (auto it = saved.begin(); it != saved.end(); ++it)
        if (it.value().isDouble() && valid(it.value().toInt()))
            games.insert(it.key(), it.value().toInt());
    if (all != m_allGames || games != m_games) {
        m_allGames = all;
        m_games = games;
        Q_EMIT changed();
    }
}

void RefreshRate::setActiveGame(const QString &appid)
{
    if (appid == m_activeGame)
        return;
    m_activeGame = appid;
    Q_EMIT activeGameChanged();
}

void RefreshRate::setAllGames(int hz)
{
    if (!m_available || !valid(hz))
        return;
    QDir().mkpath(QFileInfo(m_confPath).absolutePath());
    QSaveFile out(m_confPath);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QStringLiteral("# Device Settings' refresh rate, read by gamescope-session\nexport gamescope_refresh_hz=%1\n").arg(hz).toUtf8());
        if (!out.commit())
            qWarning("kettle-power: %s: %s", qPrintable(m_confPath), qPrintable(out.errorString()));
    }
    m_allGames = hz;
    Q_EMIT changed();
    hold();
}

void RefreshRate::setGameRate(const QString &appid, int hz)
{
    if (!m_available || appid.isEmpty() || (hz >= 0 && !valid(hz)))
        return;
    QJsonObject saved = QJsonDocument::fromJson(readAll(m_gamesPath).toUtf8()).object();
    if (hz < 0)
        saved.remove(appid);
    else
        saved.insert(appid, hz);
    // in Decky's settings, under the name of the plugin that set it first (Power)
    QDir().mkpath(QFileInfo(m_gamesPath).absolutePath());
    QSaveFile out(m_gamesPath);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QJsonDocument(saved).toJson(QJsonDocument::Indented));
        if (!out.commit())
            qWarning("kettle-power: %s: %s", qPrintable(m_gamesPath), qPrintable(out.errorString()));
    } else {
        qWarning("kettle-power: %s: %s", qPrintable(m_gamesPath), qPrintable(out.errorString()));
    }
    load();
    if (appid == m_activeGame)
        hold();
}

void RefreshRate::hold()
{
    const int hz = m_games.value(m_activeGame, m_allGames).toInt();
    // Game Mode's gamescope display: this app runs on the bottom screen's, so it's read from the
    // user manager's environment (gamescope-onready puts it there)
    auto *env = new QProcess(this);
    connect(env, &QProcess::errorOccurred, env, &QObject::deleteLater);
    connect(env, &QProcess::finished, this, [this, env, hz] {
        env->deleteLater();
        const auto m = QRegularExpression(QStringLiteral("^GAMESCOPE_WAYLAND_DISPLAY=(.+)$"), QRegularExpression::MultilineOption)
                           .match(QString::fromUtf8(env->readAllStandardOutput()));
        if (!m.hasMatch())
            return;
        auto *ctl = new QProcess(this);
        QProcessEnvironment e = QProcessEnvironment::systemEnvironment();
        e.insert(QStringLiteral("GAMESCOPE_WAYLAND_DISPLAY"), m.captured(1).trimmed());
        ctl->setProcessEnvironment(e);
        connect(ctl, &QProcess::finished, ctl, &QObject::deleteLater);
        connect(ctl, &QProcess::errorOccurred, ctl, &QObject::deleteLater);
        ctl->start(QStringLiteral("gamescopectl"), {QStringLiteral("refresh_hz"), QString::number(hz)});
    });
    env->start(QStringLiteral("systemctl"), {QStringLiteral("--user"), QStringLiteral("show-environment")});
}
