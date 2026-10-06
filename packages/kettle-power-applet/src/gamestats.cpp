// SPDX-License-Identifier: BSD-3-Clause
#include "gamestats.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QRegularExpression>
#include <QStandardPaths>

#include <algorithm>

namespace
{
// frames stop arriving when nothing is shown (the game paused, or gone): older is no reading
constexpr qint64 staleSeconds = 3;

QByteArray readFile(const QString &path)
{
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? f.readAll() : QByteArray();
}

QString steamRoot()
{
    return QDir::homePath() + QStringLiteral("/.local/share/Steam");
}

// Steam library roots, from libraryfolders.vdf, the main one first
QStringList libraries()
{
    QStringList libs = {steamRoot()};
    static const QRegularExpression pathRe(QStringLiteral("\"path\"\\s+\"([^\"]+)\""));
    const QString vdf = QString::fromUtf8(readFile(steamRoot() + QStringLiteral("/steamapps/libraryfolders.vdf")));
    for (auto it = pathRe.globalMatch(vdf); it.hasNext();) {
        const QString p = it.next().captured(1);
        if (!libs.contains(p))
            libs.append(p);
    }
    return libs;
}
}

GameStats::GameStats(QObject *parent)
    : QObject(parent)
    , m_path(qEnvironmentVariable("XDG_RUNTIME_DIR") + QStringLiteral("/kettle-fps"))
{
    m_timer.setInterval(500);
    connect(&m_timer, &QTimer::timeout, this, &GameStats::poll);
    m_timer.start();
    poll();
}

void GameStats::setHistory(int seconds)
{
    seconds = std::max(1, seconds);
    if (seconds == m_history)
        return;
    m_history = seconds;
    trim();
    Q_EMIT historyChanged();
    Q_EMIT changed();
}

void GameStats::setActive(bool active)
{
    if (active == m_timer.isActive())
        return;
    if (active) {
        m_timer.start();
        poll();
    } else {
        m_timer.stop();
    }
    Q_EMIT activeChanged();
}

void GameStats::setInterval(int ms)
{
    if (ms == m_timer.interval())
        return;
    m_timer.setInterval(ms);
    Q_EMIT intervalChanged();
}

QString GameStats::nameOf(const QString &appid) const
{
    if (appid.isEmpty())
        return {};
    static const QRegularExpression nameRe(QStringLiteral("^\\s*\"name\"\\s+\"([^\"]*)\""), QRegularExpression::MultilineOption);
    for (const QString &lib : libraries()) {
        const QByteArray acf = readFile(lib + QStringLiteral("/steamapps/appmanifest_%1.acf").arg(appid));
        const auto m = nameRe.match(QString::fromUtf8(acf));
        if (m.hasMatch())
            return m.captured(1);
    }
    return {};
}

void GameStats::identify(uint pid)
{
    m_pid = pid;
    m_appid.clear();
    m_name.clear();
    m_layer = false;
    m_fgStatus.clear();
    m_frameTimes.clear();
    if (!pid)
        return;
    const QString proc = QStringLiteral("/proc/%1/").arg(pid);
    QString runtimeDir = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
    for (const QByteArray &var : readFile(proc + QStringLiteral("environ")).split('\0')) {
        if (var.startsWith("XDG_RUNTIME_DIR="))
            runtimeDir = QString::fromUtf8(var.mid(16));
        if (var.startsWith("SteamAppId=")) {
            const QByteArray id = var.mid(11);
            if (!id.isEmpty() && id != "0")
                m_appid = QString::fromLatin1(id);
        }
    }
    m_layer = readFile(proc + QStringLiteral("maps")).contains("libVkLayer_kettle_framegen");
    // in the game's runtime dir, which Proton's container (pressure-vessel) keeps apart from
    // ours: read it through the game's root
    if (m_layer)
        m_fgStatus = proc + QStringLiteral("root") + runtimeDir + QStringLiteral("/kettle-framegen/%1").arg(pid);
    m_name = nameOf(m_appid);
    if (m_name.isEmpty())
        m_name = QString::fromUtf8(readFile(proc + QStringLiteral("comm")).trimmed());
}

// the frame times of the last `history` seconds
void GameStats::trim()
{
    double total = 0;
    qsizetype keep = 0;
    for (qsizetype i = m_frameTimes.size() - 1; i >= 0; --i) {
        total += m_frameTimes[i];
        if (total > m_history * 1000.0)
            break;
        ++keep;
    }
    m_frameTimes = m_frameTimes.mid(m_frameTimes.size() - keep);
}

void GameStats::stop()
{
    if (!m_running && !m_steamFocused && m_frameTimes.isEmpty())
        return;
    m_running = m_steamFocused = false;
    m_fps = m_frameTime = m_low1 = 0;
    m_frameTimes.clear();
    Q_EMIT changed();
}

void GameStats::poll()
{
    QHash<QByteArray, QByteArray> d;
    for (const QByteArray &line : readFile(m_path).split('\n')) {
        const qsizetype eq = line.indexOf('=');
        if (eq > 0)
            d.insert(line.left(eq), line.mid(eq + 1));
    }
    const qint64 stamp = d.value("time").toLongLong();
    const uint pid = d.value("pid").toUInt();
    if (!stamp || QDateTime::currentSecsSinceEpoch() - stamp > staleSeconds || !pid || !QFile::exists(QStringLiteral("/proc/%1").arg(pid))) {
        stop();
        return;
    }
    if (stamp == m_stamp && pid == m_pid)
        return; // nothing new yet
    m_stamp = stamp;
    if (pid != m_pid)
        identify(pid);

    m_steamFocused = d.value("steam_focused") == "1";
    m_running = !m_steamFocused;
    m_fps = d.value("fps").toDouble();
    m_refresh = d.value("refresh").toInt();

    double sum = 0;
    qsizetype n = 0;
    for (const QByteArray &t : d.value("frametimes").split(',')) {
        bool ok = false;
        const double ms = t.toDouble(&ok);
        if (ok && ms > 0) {
            m_frameTimes.append(ms);
            sum += ms;
            ++n;
        }
    }
    m_frameTime = n ? sum / n : (m_fps > 0 ? 1000.0 / m_fps : 0);
    trim();

    // 1% low: the frame rate at the 99th percentile frame time
    if (m_frameTimes.size() >= 20) {
        QList<qreal> sorted = m_frameTimes;
        std::sort(sorted.begin(), sorted.end());
        const qreal slow = sorted[std::min<qsizetype>(sorted.size() - 1, sorted.size() * 99 / 100)];
        m_low1 = slow > 0 ? 1000.0 / slow : 0;
    } else {
        m_low1 = 0;
    }

    // the multiplier in use, as the layer reports it (with multiplier = auto it changes as the
    // game runs)
    m_frameGen = 0;
    if (!m_fgStatus.isEmpty()) {
        static const QRegularExpression multRe(QStringLiteral("^multiplier=(\\d+)"), QRegularExpression::MultilineOption);
        const auto m = multRe.match(QString::fromLatin1(readFile(m_fgStatus)));
        if (m.hasMatch())
            m_frameGen = m.captured(1).toInt();
    }
    Q_EMIT changed();
}
