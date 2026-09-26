// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include <QObject>
#include <QStringList>
#include <QTimer>

#include <functional>

class QQuickWindow;

// What the QML side can't do itself: start apps and settings modules, remember the "show at
// login" choice, set what the device starts up in, and run welcome-flatpak (Gaming Extras)
// without blocking the UI.
class Backend : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool showAtLogin READ showAtLogin WRITE setShowAtLogin NOTIFY showAtLoginChanged)
    Q_PROPERTY(QStringList installedApps READ installedApps NOTIFY installedAppsChanged)
    // welcome-flatpak's status line: idle | running I N ID | done N | error ID MESSAGE
    Q_PROPERTY(QString installStatus READ installStatus NOTIFY installStatusChanged)
    Q_PROPERTY(QString screenshotDir READ screenshotDir CONSTANT)
    // steamos-manager's default login mode: game | desktop, empty while unknown
    Q_PROPERTY(QString bootMode READ bootMode WRITE setBootMode NOTIFY bootModeChanged)

public:
    explicit Backend(const QString &screenshotDir, QObject *parent = nullptr);

    bool showAtLogin() const;
    void setShowAtLogin(bool show);
    QStringList installedApps() const { return m_installedApps; }
    QString installStatus() const { return m_installStatus; }
    QString screenshotDir() const { return m_screenshotDir; }
    QString bootMode() const { return m_bootMode; }
    void setBootMode(const QString &mode);

    Q_INVOKABLE bool hasApp(const QString &desktopId) const;
    Q_INVOKABLE void launchApp(const QString &desktopId);
    // a System Settings module in a window of its own (kcmshell6), e.g. "kcm_users"
    Q_INVOKABLE void openSettings(const QString &module);
    Q_INVOKABLE void openSystemSettings();
    Q_INVOKABLE void returnToGameMode();

    Q_INVOKABLE void installApps(const QStringList &ids);
    Q_INVOKABLE void refreshApps();

    Q_INVOKABLE bool saveScreenshot(QQuickWindow *window, const QString &name);

Q_SIGNALS:
    void showAtLoginChanged();
    void installedAppsChanged();
    void installStatusChanged();
    void bootModeChanged();
    // a second start (menu entry, Gaming Extras entry) asks the open window to show a page
    void pageRequested(const QString &page);

private:
    void run(const QString &program, const QStringList &args, std::function<void(int, const QString &, const QString &)> done);
    void runHelper(const QStringList &args, std::function<void(int, const QString &, const QString &)> done);
    void refreshBootMode();
    void pollStatus();
    void setInstallStatus(const QString &status);

    QString m_screenshotDir;
    QStringList m_installedApps;
    QString m_installStatus = QStringLiteral("idle");
    QString m_bootMode;
    QTimer m_poll;
};
