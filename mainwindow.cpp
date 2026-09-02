#include "mainwindow.h"

#include <QDebug>
#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFrame>
#include <QHeaderView>
#include <QFileInfo>
#include <QDir>
#include <QPalette>
#include <QColor>
#include <QPen>
#include <QFont>

namespace {
const QString SAFE = "#3ddc84";
const QString DROP = "#ff5a5a";
const QString WARN = "#ffb300";
const QString BG = "#14171c";
const QString PANEL = "#1e232b";
const QString PANEL2 = "#252b34";
const QString TXT = "#e7eaee";
const QString MUTED = "#8b94a0";
constexpr double SAFETY_LIMIT_PSI = 150.0;
}

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent) {
    // same log file the Python side (decision_engine.py / gateway.py) and
    // the Rust gateway (gateway.rs) all write to - the actual "bridge"
    // between every implementation in this project. No IPC, just a
    // shared file, so it doesn't matter which language produced the row.
    logPath = QDir::currentPath() + "/voltguard_log.csv";
    // launch_voltguard.py polls for this file's existence and shuts down
    // every component (PLC, gateway, traffic) when it appears - a file
    // is a simple, reliable way for a separate GUI process to signal a
    // separate orchestrator process without needing sockets or IPC libs
    stopSignalPath = QDir::currentPath() + "/voltguard.stop";

    setWindowTitle("VoltGuard - Native Traffic Log (Qt/C++)");
    resize(1150, 820);

    applyDarkTheme();
    buildUi();

    pollTimer = new QTimer(this);
    connect(pollTimer, &QTimer::timeout, this, &MainWindow::pollLogFile);
    pollTimer->start(400);

    freshnessTimer = new QTimer(this);
    connect(freshnessTimer, &QTimer::timeout, this, &MainWindow::updateFreshnessLabel);
    freshnessTimer->start(1000);

    // global shortcuts - QShortcut works regardless of which child widget
    // (the table, in practice) currently has keyboard focus, unlike
    // overriding keyPressEvent, which only fires if nothing else consumes
    // the key first
    auto *kioskShortcut = new QShortcut(QKeySequence(Qt::Key_F11), this);
    connect(kioskShortcut, &QShortcut::activated, this, &MainWindow::toggleKioskMode);
    auto *exitKioskShortcut = new QShortcut(QKeySequence(Qt::Key_Escape), this);
    connect(exitKioskShortcut, &QShortcut::activated, this, [this]() {
        if (kioskMode) toggleKioskMode();
    });
}

void MainWindow::applyDarkTheme() {
    setStyleSheet(QString(
        "QMainWindow { background-color: %1; }"
        "QWidget { background-color: %1; color: %2; }"
        "QTableWidget { background-color: %3; gridline-color: #2e3540; "
        "  border: 1px solid #2e3540; font-family: Consolas, monospace; }"
        "QHeaderView::section { background-color: %4; color: %5; "
        "  padding: 6px; border: none; font-weight: bold; }"
        "QTableWidget::item { padding: 4px; }"
    ).arg(BG, TXT, PANEL, PANEL2, MUTED));
}

void MainWindow::buildUi() {
    auto *central = new QWidget(this);
    setCentralWidget(central);
    auto *root = new QVBoxLayout(central);
    root->setContentsMargins(18, 16, 18, 12);
    root->setSpacing(10);

    // ---- header ----
    auto *headerRow = new QHBoxLayout();
    auto *title = new QLabel("VoltGuard", this);
    title->setStyleSheet(QString("font-size: 24px; font-weight: bold; color: %1;").arg(SAFE));
    auto *subtitle = new QLabel("  native Qt/C++ traffic log", this);
    subtitle->setStyleSheet(QString("font-size: 12px; color: %1;").arg(MUTED));
    headerRow->addWidget(title);
    headerRow->addWidget(subtitle);
    headerRow->addStretch();

    clearViewButton = new QPushButton("Clear View", this);
    clearViewButton->setStyleSheet(QString(
        "QPushButton { background-color: %1; color: %2; border: 1px solid #3a4150; "
        "  border-radius: 4px; padding: 6px 14px; font-size: 11px; } "
        "QPushButton:hover { background-color: #2f3644; }"
    ).arg(PANEL2, TXT));
    connect(clearViewButton, &QPushButton::clicked, this, &MainWindow::onClearViewClicked);
    headerRow->addWidget(clearViewButton);

    stopAllButton = new QPushButton("Stop All", this);
    stopAllButton->setStyleSheet(QString(
        "QPushButton { background-color: #3a1616; color: %1; border: 1px solid %2; "
        "  border-radius: 4px; padding: 6px 14px; font-size: 11px; font-weight: bold; } "
        "QPushButton:hover { background-color: #4a1c1c; }"
    ).arg(DROP, DROP));
    connect(stopAllButton, &QPushButton::clicked, this, &MainWindow::onStopAllClicked);
    headerRow->addWidget(stopAllButton);

    auto *kioskHint = new QLabel("  F11: factory-floor mode", this);
    kioskHint->setStyleSheet(QString("font-size: 10px; color: %1;").arg(MUTED));
    headerRow->addWidget(kioskHint);
    root->addLayout(headerRow);

    // ---- status banner ----
    bannerLabel = new QLabel("WAITING FOR TRAFFIC...", this);
    bannerLabel->setAlignment(Qt::AlignCenter);
    bannerLabel->setMinimumHeight(50);
    bannerLabel->setStyleSheet(QString(
        "font-size: 15px; font-weight: bold; color: %1; "
        "background-color: %2; border-radius: 4px;"
    ).arg(MUTED, PANEL2));
    root->addWidget(bannerLabel);

    // ---- freshness indicator - answers "is this actually live" at a
    // glance, which is exactly the question a stale log file can't
    // answer for itself ----
    freshnessLabel = new QLabel("\u25cf no data yet", this);
    freshnessLabel->setStyleSheet(QString("font-size: 10px; color: %1;").arg(MUTED));
    root->addWidget(freshnessLabel);

    // ---- stat boxes ----
    auto *statsRow = new QHBoxLayout();
    statsRow->setSpacing(10);

    auto makeStatBox = [&](const QString &color) -> QLabel* {
        auto *box = new QFrame(this);
        box->setStyleSheet(QString("background-color: %1; border-radius: 4px;").arg(PANEL2));
        auto *v = new QVBoxLayout(box);
        auto *value = new QLabel("0", box);
        value->setAlignment(Qt::AlignCenter);
        value->setStyleSheet(QString("font-size: 26px; font-weight: bold; color: %1; border: none;").arg(color));
        v->addWidget(value);
        statsRow->addWidget(box);
        return value;
    };

    allowValueLabel = makeStatBox(SAFE);
    dropValueLabel = makeStatBox(DROP);
    totalValueLabel = makeStatBox(TXT);
    root->addLayout(statsRow);

    QStringList captions = {"COMMANDS ALLOWED", "COMMANDS BLOCKED", "TOTAL INSPECTED"};
    auto *capRow = new QHBoxLayout();
    for (const auto &c : captions) {
        auto *cap = new QLabel(c, this);
        cap->setAlignment(Qt::AlignCenter);
        cap->setStyleSheet(QString("font-size: 9px; color: %1;").arg(MUTED));
        capRow->addWidget(cap);
    }
    root->addLayout(capRow);

    // ---- week 3: real-time predicted vs actual pressure chart ----
    auto *chartLabel = new QLabel("Predicted vs. Actual Pressure (live PLC telemetry)", this);
    chartLabel->setStyleSheet("font-size: 12px; font-weight: bold;");
    root->addWidget(chartLabel);

    auto *chart = new QChart();
    chart->setBackgroundBrush(QBrush(QColor(PANEL)));
    chart->setBackgroundRoundness(6);
    chart->legend()->setLabelColor(QColor(TXT));
    chart->legend()->setVisible(true);
    chart->setMargins(QMargins(6, 6, 6, 6));

    predictedSeries = new QLineSeries();
    predictedSeries->setName("Predicted");
    predictedSeries->setPen(QPen(QColor(SAFE), 2));

    actualSeries = new QLineSeries();
    actualSeries->setName("Actual (PLC telemetry)");
    actualSeries->setPen(QPen(QColor("#6c8eef"), 2));

    chart->addSeries(predictedSeries);
    chart->addSeries(actualSeries);

    axisX = new QValueAxis();
    axisX->setLabelsColor(QColor(MUTED));
    axisX->setGridLineColor(QColor("#2e3540"));
    axisX->setTitleText("command #");
    axisX->setTitleBrush(QBrush(QColor(MUTED)));
    axisX->setRange(0, MAX_CHART_POINTS);

    axisY = new QValueAxis();
    axisY->setLabelsColor(QColor(MUTED));
    axisY->setGridLineColor(QColor("#2e3540"));
    axisY->setTitleText("psi");
    axisY->setTitleBrush(QBrush(QColor(MUTED)));
    axisY->setRange(0, SAFETY_LIMIT_PSI * 1.3);

    chart->addAxis(axisX, Qt::AlignBottom);
    chart->addAxis(axisY, Qt::AlignLeft);
    predictedSeries->attachAxis(axisX);
    predictedSeries->attachAxis(axisY);
    actualSeries->attachAxis(axisX);
    actualSeries->attachAxis(axisY);

    chartView = new QChartView(chart, this);
    chartView->setRenderHint(QPainter::Antialiasing);
    chartView->setMinimumHeight(220);
    chartView->setBackgroundBrush(QBrush(QColor(BG)));
    root->addWidget(chartView);

    // ---- log table ----
    auto *tableLabel = new QLabel("Live Traffic Log (tailing voltguard_log.csv)", this);
    tableLabel->setStyleSheet("font-size: 12px; font-weight: bold;");
    root->addWidget(tableLabel);

    logTable = new QTableWidget(0, 6, this);
    logTable->setHorizontalHeaderLabels({"Time", "Verdict", "Pump RPM", "Predicted PSI", "Actual PSI", "Reason"});
    logTable->horizontalHeader()->setSectionResizeMode(5, QHeaderView::Stretch);
    for (int i = 0; i < 5; ++i)
        logTable->horizontalHeader()->setSectionResizeMode(i, QHeaderView::ResizeToContents);
    logTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    logTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    logTable->verticalHeader()->setVisible(false);
    root->addWidget(logTable, /*stretch=*/1);

    // ---- status line ----
    statusLabel = new QLabel(QString("watching: %1").arg(logPath), this);
    statusLabel->setStyleSheet(QString("font-size: 9px; color: %1;").arg(MUTED));
    root->addWidget(statusLabel);
}

void MainWindow::toggleKioskMode() {
    // Factory-floor readability mode: fullscreen, larger fonts throughout,
    // so an operator can register status from across the room instead of
    // needing to be at the keyboard. F11 to enter, F11 or Esc to leave.
    kioskMode = !kioskMode;

    if (kioskMode) {
        showFullScreen();
        bannerLabel->setStyleSheet(bannerLabel->styleSheet().replace("font-size: 15px", "font-size: 26px"));
        for (auto *label : {allowValueLabel, dropValueLabel, totalValueLabel}) {
            QFont f = label->font();
            f.setPointSize(f.pointSize() + 16);
            label->setFont(f);
        }
        QFont tableFont = logTable->font();
        tableFont.setPointSize(tableFont.pointSize() + 3);
        logTable->setFont(tableFont);
        statusLabel->setText(statusLabel->text() + "   [F11 or Esc to exit kiosk mode]");
    } else {
        showNormal();
        bannerLabel->setStyleSheet(bannerLabel->styleSheet().replace("font-size: 26px", "font-size: 15px"));
        for (auto *label : {allowValueLabel, dropValueLabel, totalValueLabel}) {
            QFont f = label->font();
            f.setPointSize(f.pointSize() - 16);
            label->setFont(f);
        }
        QFont tableFont = logTable->font();
        tableFont.setPointSize(tableFont.pointSize() - 3);
        logTable->setFont(tableFont);
    }
}

void MainWindow::pollLogFile() {
    QFile file(logPath);

    if (!file.exists()) {
        statusLabel->setText(QString("waiting for %1 to be created - run main_sim.py, "
                                      "network_demo.py, gateway.py, or the Rust gateway").arg(logPath));
        return;
    }

    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        statusLabel->setText("could not open log file for reading");
        return;
    }

    // if the file shrank (someone deleted/reset it), start over from zero
    if (file.size() < lastReadPos) {
        lastReadPos = 0;
        headerSkipped = false;
        logTable->setRowCount(0);
        allowCount = dropCount = malformedCount = 0;
        chartPointIndex = 0;
        predictedSeries->clear();
        actualSeries->clear();
    }

    file.seek(lastReadPos);
    QByteArray newBytes = file.readAll();
    lastReadPos = file.pos();
    file.close();

    if (newBytes.isEmpty()) return;

    const auto lines = QString::fromUtf8(newBytes).split('\n', Qt::SkipEmptyParts);
    for (const QString &rawLine : lines) {
        const QString line = rawLine.trimmed(); // csv module writes \r\n even on Linux/macOS
        if (line.isEmpty()) continue;
        if (!headerSkipped) {
            headerSkipped = true; // first line in the file is the CSV header
            continue;
        }
        const QStringList fields = line.split(',');
        // timestamp,verdict,rpm,target_pressure,peak_predicted_pressure,actual_pressure,reason
        if (fields.size() < 7) continue; // malformed/partial line, skip it
        handleNewRow(fields);
    }

    allowValueLabel->setText(QString::number(allowCount));
    dropValueLabel->setText(QString::number(dropCount));
    totalValueLabel->setText(QString::number(allowCount + dropCount + malformedCount));
    statusLabel->setText(QString("watching: %1  (%2 rows loaded)")
                              .arg(logPath).arg(logTable->rowCount()));
}

void MainWindow::updateChart(double predicted, double actual) {
    predictedSeries->append(chartPointIndex, predicted);
    actualSeries->append(chartPointIndex, actual);
    chartPointIndex++;

    // keep a rolling window instead of growing forever
    if (predictedSeries->count() > MAX_CHART_POINTS) {
        predictedSeries->remove(0);
    }
    if (actualSeries->count() > MAX_CHART_POINTS) {
        actualSeries->remove(0);
    }

    int minX = qMax(0, chartPointIndex - MAX_CHART_POINTS);
    axisX->setRange(minX, minX + MAX_CHART_POINTS);

    double maxSeen = qMax(predicted, actual);
    double currentTop = axisY->max();
    if (maxSeen > currentTop * 0.9) {
        axisY->setRange(0, maxSeen * 1.3);
    }
}

void MainWindow::handleNewRow(const QStringList &fields) {
    timeSinceLastRow.restart();
    haveSeenAnyRow = true;

    // CSV columns: timestamp, verdict, rpm, target_pressure,
    // peak_predicted_pressure, actual_pressure, reason
    const QString timestamp = fields[0];
    const QString verdict = fields[1];
    const QString rpm = fields[2];
    const QString predictedPsi = fields[4];
    const QString actualPsiStr = fields[5];
    const QString reason = fields.mid(6).join(','); // reason may itself contain commas

    QString rowColor = TXT;
    if (verdict == "ALLOW") { allowCount++; rowColor = SAFE; }
    else if (verdict == "DROP") { dropCount++; rowColor = DROP; }
    else { malformedCount++; rowColor = WARN; }

    logTable->insertRow(0);
    QStringList cols = {timestamp, verdict, rpm, predictedPsi,
                         actualPsiStr.isEmpty() ? QString("\u2014") : actualPsiStr, reason};
    for (int i = 0; i < cols.size(); ++i) {
        auto *item = new QTableWidgetItem(cols[i]);
        item->setForeground(QColor(rowColor));
        if (i == 1) {
            QFont f = item->font();
            f.setBold(true);
            item->setFont(f);
        }
        logTable->setItem(0, i, item);
    }

    bool hasActual = !actualPsiStr.isEmpty();
    if (verdict == "ALLOW" && hasActual) {
        // only ALLOW commands have both a prediction and a real measured
        // outcome - DROP predictions can be in the tens of thousands of
        // psi and would swamp the chart's scale, and there's no "actual"
        // to compare against since a dropped command never executed.
        // This keeps the chart a genuine model-validation view: does the
        // physics prediction track what the PLC actually measured, for
        // the traffic that was actually allowed to run.
        double predicted = predictedPsi.toDouble();
        double actual = actualPsiStr.toDouble();
        updateChart(predicted, actual);
    }

    if (verdict == "DROP") {
        bannerLabel->setText(QString("COMMAND BLOCKED - %1 RPM predicted %2 psi, exceeds safety limit")
                                  .arg(rpm, predictedPsi));
        bannerLabel->setStyleSheet(QString(
            "font-size: 15px; font-weight: bold; color: %1; "
            "background-color: #3a1616; border-radius: 4px;").arg(DROP));
    } else if (verdict == "ALLOW") {
        bannerLabel->setText("ALL SYSTEMS NORMAL - NO THREATS DETECTED");
        bannerLabel->setStyleSheet(QString(
            "font-size: 15px; font-weight: bold; color: %1; "
            "background-color: #0f3d24; border-radius: 4px;").arg(SAFE));
    }
}

void MainWindow::updateFreshnessLabel() {
    if (!haveSeenAnyRow) {
        freshnessLabel->setText("\u25cf no data yet - waiting for traffic");
        freshnessLabel->setStyleSheet(QString("font-size: 10px; color: %1;").arg(MUTED));
        return;
    }

    qint64 secs = timeSinceLastRow.elapsed() / 1000;
    QString text;
    QString color;

    if (secs < 5) {
        text = QString("\u25cf LIVE - last update %1s ago").arg(secs);
        color = SAFE;
    } else if (secs < 30) {
        text = QString("\u25cf slowing - last update %1s ago").arg(secs);
        color = WARN;
    } else {
        // this is exactly the situation that caused earlier confusion:
        // a real file being watched, but nothing new has landed in it
        // for a long time - say so plainly instead of looking "live"
        // forever off old data
        qint64 mins = secs / 60;
        QString ago = mins > 0 ? QString("%1m %2s ago").arg(mins).arg(secs % 60)
                                : QString("%1s ago").arg(secs);
        text = QString("\u25cf STALE - no new data for %1 - is a gateway actually running?").arg(ago);
        color = DROP;
    }

    freshnessLabel->setText(text);
    freshnessLabel->setStyleSheet(QString("font-size: 10px; font-weight: bold; color: %1;").arg(color));
}

void MainWindow::onClearViewClicked() {
    // resets the on-screen view only - does NOT touch voltguard_log.csv,
    // so this is safe to click anytime without losing the real record
    logTable->setRowCount(0);
    allowCount = dropCount = malformedCount = 0;
    allowValueLabel->setText("0");
    dropValueLabel->setText("0");
    totalValueLabel->setText("0");
    predictedSeries->clear();
    actualSeries->clear();
    chartPointIndex = 0;
    axisX->setRange(0, MAX_CHART_POINTS);
    axisY->setRange(0, SAFETY_LIMIT_PSI * 1.3);
    bannerLabel->setText("WAITING FOR TRAFFIC...");
    bannerLabel->setStyleSheet(QString(
        "font-size: 15px; font-weight: bold; color: %1; "
        "background-color: %2; border-radius: 4px;").arg(MUTED, PANEL2));
    statusLabel->setText(QString("watching: %1  (view cleared - underlying log file untouched)").arg(logPath));
}

void MainWindow::onStopAllClicked() {
    auto reply = QMessageBox::question(
        this, "Stop VoltGuard",
        "This will stop the PLC, gateway, and traffic generator, and close this dashboard.\n\n"
        "Are you sure you want to stop everything?",
        QMessageBox::Yes | QMessageBox::No, QMessageBox::No);

    if (reply != QMessageBox::Yes) {
        return;
    }

    // write the signal file launch_voltguard.py is watching for - it
    // polls for this once a second and shuts every component down
    // cleanly when it appears, same as it does for Ctrl+C
    QFile stopFile(stopSignalPath);
    if (stopFile.open(QIODevice::WriteOnly)) {
        stopFile.write("stop requested from dashboard\n");
        stopFile.close();
    }

    bannerLabel->setText("STOPPING ALL COMPONENTS...");
    bannerLabel->setStyleSheet(QString(
        "font-size: 15px; font-weight: bold; color: %1; "
        "background-color: #3a1616; border-radius: 4px;").arg(DROP));

    // give the launcher a moment to see the signal file and start
    // shutting other components down before this window itself closes
    QTimer::singleShot(1200, this, &QWidget::close);
}
