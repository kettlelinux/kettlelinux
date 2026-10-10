// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>
#include <qqmlregistration.h>

// The top screen's refresh rate in Game Mode, as Device Settings > Power (the all-games rate) and
// Game Settings > Perf (a game's own, held while it runs) set it, through the same files, so a
// change made in either shows here (the plugins' shared/refresh.py):
//   /usr/lib/kettle/refresh-rates                  the rates the panel has
//   ~/.config/kettle/refresh-rate.conf             the all-games rate, gamescope-session starts at it
//   ~/homebrew/settings/kettle-power/refresh-rates.json   games' own, {appid: Hz}
// 0 is Auto: Steam's frame limit picks the rate. A change is made live with gamescopectl
// refresh_hz on Game Mode's gamescope, whose display the user manager's environment names.
class RefreshRate : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    // in Game Mode on the bottom screen (KETTLE_BOTTOM_SHELL), with more than one rate to pick
    Q_PROPERTY(bool available READ available CONSTANT)
    Q_PROPERTY(QVariantList rates READ rates CONSTANT)
    // the all-games rate (0: Auto)
    Q_PROPERTY(int allGames READ allGames NOTIFY changed)
    // the games with their own rate, {appid: Hz}
    Q_PROPERTY(QVariantMap games READ games NOTIFY changed)
    // the running game (PowerBackend.activeGame), whose own rate is held while it runs
    Q_PROPERTY(QString activeGame READ activeGame WRITE setActiveGame NOTIFY activeGameChanged)

public:
    explicit RefreshRate(QObject *parent = nullptr);

    bool available() const { return m_available; }
    QVariantList rates() const { return m_rates; }
    int allGames() const { return m_allGames; }
    QVariantMap games() const { return m_games; }
    QString activeGame() const { return m_activeGame; }
    void setActiveGame(const QString &appid);

    Q_INVOKABLE void setAllGames(int hz);
    // hz < 0: the game follows the all-games rate
    Q_INVOKABLE void setGameRate(const QString &appid, int hz);

Q_SIGNALS:
    void changed();
    void activeGameChanged();

private:
    void load();
    bool valid(int hz) const;
    // the running game's own rate, else the all-games one, set on Game Mode's gamescope
    void hold();

    QTimer m_timer;
    QString m_confPath;
    QString m_gamesPath;
    bool m_available = false;
    QVariantList m_rates;
    int m_default = 0; // the rate gamescope-session starts at with none picked
    int m_allGames = 0;
    QVariantMap m_games;
    QString m_activeGame;
};
