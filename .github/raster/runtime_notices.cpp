// Preserve the SDK's required ownership notice in the application's About box.
#include <QCoreApplication>
#include <QDialog>
#include <QEvent>
#include <QLabel>
#include <QLayout>
#include <QUrl>
#include <QVariant>

namespace {
class NoticeFilter final : public QObject {
 public:
  explicit NoticeFilter(QObject* parent) : QObject(parent) {}

 protected:
  bool eventFilter(QObject* object, QEvent* event) override {
    if (event->type() == QEvent::Show && object->inherits("CAbout") &&
        !object->property("qmsCiNoticesAdded").toBool()) {
      auto* dialog = qobject_cast<QDialog*>(object);
      if (dialog && dialog->layout()) {
        const QString notice = QStringLiteral(
            "This application supports the ECW data format and ECWP compression protocols. "
            "Portions of this computer program are Copyright 2007-2013 Intergraph Corporation. "
            "All rights reserved. Creating compressed files using ECW technology is protected "
            "by one or more of U.S. Patent No. 6,201,897, No. 6,442,298 and No. 6,633,688.");
        const QUrl url = QUrl::fromLocalFile(QCoreApplication::applicationDirPath() + "/3rdparty.txt");
        auto* label = new QLabel(notice.toHtmlEscaped() + "<br><a href=\"" +
                                url.toString().toHtmlEscaped() + "\">Third-party notices and licenses</a>", dialog);
        label->setWordWrap(true);
        label->setOpenExternalLinks(true);
        dialog->layout()->addWidget(label);
        object->setProperty("qmsCiNoticesAdded", true);
      }
    }
    return QObject::eventFilter(object, event);
  }
};

void installNotices() {
  auto* application = QCoreApplication::instance();
  application->installEventFilter(new NoticeFilter(application));
}
}  // namespace

Q_COREAPP_STARTUP_FUNCTION(installNotices)
