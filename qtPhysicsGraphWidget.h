// PhysicsGraphWidget.h
//
// Week 3 "Visualizing Physics": plots predicted vs. actual physical state
// in real time by connecting to the Rust IPS engine's telemetry stream
// (127.0.0.1:9001, newline-delimited JSON — see main.rs TelemetryFrame).
//
// Add this widget to your Week 2 native Qt dashboard's main window
// (e.g. as a tab or a docked panel).
//
// Requires the Qt Charts module: add `QT += charts` to your .pro file,
// or find_package(Qt6 COMPONENTS Charts) in CMake.

#pragma once

#include <QWidget>
#include <QTcpSocket>
#include <QtCharts/QChart>
#include <QtCharts/QChartView>
#include <QtCharts/QLineSeries>
#include <QtCharts/QValueAxis>
#include <QLabel>

class PhysicsGraphWidget : public QWidget {
    Q_OBJECT

public:
    explicit PhysicsGraphWidget(QWidget *parent = nullptr);

private slots:
    void connectToEngine();
    void onReadyRead();
    void onSocketError(QAbstractSocket::SocketError error);

private:
    void appendFrame(double predicted, double actual, const QString &verdict,
                      qint64 latencyUs, quint64 timestampMs);

    QTcpSocket *m_socket;
    QByteArray m_recvBuffer;

    QtCharts::QChart *m_chart;
    QtCharts::QChartView *m_chartView;
    QtCharts::QLineSeries *m_predictedSeries;
    QtCharts::QLineSeries *m_actualSeries;
    QtCharts::QValueAxis *m_axisX;
    QtCharts::QValueAxis *m_axisY;

    QLabel *m_statusLabel;   // connection / last-verdict status
    QLabel *m_latencyLabel;  // rolling latency readout for the sub-10ms proof

    double m_xCounter = 0.0;
    static constexpr int kMaxVisiblePoints = 200; // rolling window
};