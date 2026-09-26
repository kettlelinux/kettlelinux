// SPDX-License-Identifier: BSD-3-Clause
// Kettle Welcome: the desktop's welcome and hub. Opens on a user's first desktop login
// (--autostart, from /etc/xdg/autostart), then from the application menu whenever needed.
#include <QApplication>
#include <QCommandLineParser>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QQuickWindow>

#include <KAboutData>
#include <KConfigGroup>
#include <KDBusService>
#include <KSharedConfig>
#include <KWindowSystem>

#include "backend.h"

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE"))
        QQuickStyle::setStyle(QStringLiteral("org.kde.desktop"));

    KAboutData about(QStringLiteral("kettle-welcome"), QStringLiteral("Kettle Welcome"), QStringLiteral(KETTLE_VERSION),
                     QStringLiteral("Set up Kettle Linux and find your way around"), KAboutLicense::BSDL);
    about.setDesktopFileName(QStringLiteral("org.kettle.Welcome"));
    KAboutData::setApplicationData(about);
    QApplication::setWindowIcon(QIcon(QStringLiteral(KETTLE_ICON)));

    QCommandLineParser parser;
    about.setupCommandLine(&parser);
    const QCommandLineOption autostartOpt(QStringLiteral("autostart"),
                                          QStringLiteral("Login start: only on the first login, or when \"Show at every login\" is on."));
    const QCommandLineOption pageOpt(QStringLiteral("page"), QStringLiteral("Page to open: home, setup, controls, games, extras, system."),
                                     QStringLiteral("page"), QStringLiteral("home"));
    const QCommandLineOption screenshotOpt(QStringLiteral("screenshot"), QStringLiteral("Save each page as DIR/<page>.png and quit (development)."),
                                           QStringLiteral("dir"));
    parser.addOptions({autostartOpt, pageOpt, screenshotOpt});
    parser.process(app);
    about.processCommandLine(&parser);

    if (parser.isSet(autostartOpt)) {
        KConfigGroup g = KSharedConfig::openConfig(QStringLiteral("kettle-welcomerc"))->group(QStringLiteral("General"));
        if (g.readEntry("FirstRunDone", false) && !g.readEntry("ShowAtLogin", false))
            return 0;
        g.writeEntry("FirstRunDone", true);
        g.sync();
    }

    // one window: starting it again (menu, Gaming Extras entry) raises it on the asked-for page
    KDBusService service(KDBusService::Unique);

    Backend backend(parser.value(screenshotOpt));
    QQmlApplicationEngine engine;
    qmlRegisterSingletonInstance("org.kettle.welcome", 1, 0, "Backend", &backend);
    engine.rootContext()->setContextProperty(QStringLiteral("startPage"), parser.value(pageOpt));
    engine.loadFromModule("org.kettle.welcome", "Main");
    if (engine.rootObjects().isEmpty())
        return 1;
    auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());

    QObject::connect(&service, &KDBusService::activateRequested, &backend, [&](const QStringList &args, const QString &) {
        QCommandLineParser again;
        again.addOptions({autostartOpt, pageOpt, screenshotOpt});
        again.parse(args);
        if (again.isSet(autostartOpt))
            return;
        if (again.isSet(pageOpt))
            Q_EMIT backend.pageRequested(again.value(pageOpt));
        if (window) {
            KWindowSystem::updateStartupId(window);
            window->show();
            window->raise();
            KWindowSystem::activateWindow(window);
        }
    });

    return app.exec();
}
