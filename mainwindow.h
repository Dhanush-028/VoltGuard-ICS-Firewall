#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QLabel>
#include <QTableWidget>
#include <QTimer>
#include <QFile>
#include <QString>
#include <QKeyEvent>
#include <QShortcut>
#include <QPushButton>
#include <QMessageBox>
#include <QElapsedTimer>
#include <QDir>
#include <QtCharts/QChart>
#include <QtCharts/QChartView>
#include <QtCharts/QLineSeries>
#include <QtCharts/QValueAxis>

#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
QT_CHARTS_USE_NAMESPACE
#endif

// VoltGuard native Qt/C++ dashboard.
//
// This deliberately does NOT talk to the Python decision engine over IPC.
// It tails voltguard_log.csv, the same log file gateway.py, gateway.rs,
// and decision_engine.py all write to. That keeps the C++ side completely
// decoupled from whichever language's gateway is running.
//
// Week 3 adds the real-time predicted-vs-actual pressure chart - actual
// values come from real PLC telemetry (mock_plc.py's simulated sensor
// reading), not a fabricated second line.

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget *parent = nullptr);

private slots:
    void pollLogFile();
    void onStopAllClicked();
    void onClearViewClicked();
    void updateFreshnessLabel();

private:
    void buildUi();
    void applyDarkTheme();
    void handleNewRow(const QStringList &fields);
    void updateChart(double predicted, double actual);
    void toggleKioskMode();

    QLabel *bannerLabel;
    QLabel *allowValueLabel;
    QLabel *dropValueLabel;
    QLabel *totalValueLabel;
    QLabel *statusLabel;
    QLabel *freshnessLabel;
    QTableWidget *logTable;
    QPushButton *stopAllButton;
    QPushButton *clearViewButton;

    QChartView *chartView;
    QLineSeries *predictedSeries;
    QLineSeries *actualSeries;
    QValueAxis *axisX;
    QValueAxis *axisY;
    int chartPointIndex = 0;
    static constexpr int MAX_CHART_POINTS = 60;

    QTimer *pollTimer;
    qint64 lastReadPos = 0;
    int allowCount = 0;
    int dropCount = 0;
    int malformedCount = 0;
    bool headerSkipped = false;

    QString logPath;
    QString stopSignalPath;
    bool kioskMode = false;
    QElapsedTimer timeSinceLastRow;
    bool haveSeenAnyRow = false;
    QTimer *freshnessTimer;
};

#endif // MAINWINDOW_H
