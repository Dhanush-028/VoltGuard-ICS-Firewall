// PhysicsGraphWidget.cpp

#include "PhysicsGraphWidget.h"

#include <QVBoxLayout>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QTimer>

using namespace QtCharts;

PhysicsGraphWidget::PhysicsGraphWidget(QWidget *parent) : QWidget(parent) {
    m_predictedSeries = new QLineSeries();
    m_predictedSeries->setName("Predicted physical state");

    m_actualSeries = new QLineSeries();
    m_actualSeries->setName("Actual physical state");

    m_chart = new QChart();
    m_chart->addSeries(m_predictedSeries);
    m_chart->addSeries(m_actualSeries);
    m_chart->setTitle("VoltGuard — Predicted vs. Actual Physical State");
    m_chart->legend()->setVisible(true);

    m_axisX = new QValueAxis();
    m_axisX->setTitleText("Sample");
    m_axisX->setLabelFormat("%d");

    m_axisY = new QValueAxis();
    m_axisY->setTitleText("Physical state (e.g. pressure / valve RPM)");

    m_chart->addAxis(m_axisX, Qt::AlignBottom);
    m_chart->addAxis(m_axisY, Qt::AlignLeft);
    m_predictedSeries->attachAxis(m_axisX);
    m_predictedSeries->attachAxis(m_axisY);
    m_actualSeries->attachAxis(m_axisX);
    m_actualSeries->attachAxis(m_axisY);

    m_chartView = new QChartView(m_chart);
    m_chartView->setRenderHint(QPainter::Antialiasing);

    m_statusLabel = new QLabel("Connecting to VoltGuard engine...");
    m_latencyLabel = new QLabel("Latency: --");

    auto *layout = new QVBoxLayout(this);
    layout->addWidget(m_chartView);
    layout->addWidget(m_statusLabel);
    layout->addWidget(m_latencyLabel);
    setLayout(layout);

    m_socket = new QTcpSocket(this);
    connect(m_socket, &QTcpSocket::readyRead, this, &PhysicsGraphWidget::onReadyRead);
    connect(m_socket, &QTcpSocket::errorOccurred, this, &PhysicsGraphWidget::onSocketError);
    connect(m_socket, &QTcpSocket::connected, this, [this]() {
        m_statusLabel->setText("Connected to VoltGuard IPS engine");
    });

    connectToEngine();

    // Auto-reconnect if the engine restarts.
    auto *reconnectTimer = new QTimer(this);
    connect(reconnectTimer, &QTimer::timeout, this, [this]() {
        if (m_socket->state() == QAbstractSocket::UnconnectedState) {
            connectToEngine();
        }
    });
    reconnectTimer->start(2000);
}

void PhysicsGraphWidget::connectToEngine() {
    // Matches the Rust telemetry server bound in main.rs (run_telemetry_server).
    m_socket->connectToHost("127.0.0.1", 9001);
}

void PhysicsGraphWidget::onReadyRead() {
    m_recvBuffer.append(m_socket->readAll());

    int newlineIdx;
    while ((newlineIdx = m_recvBuffer.indexOf('\n')) != -1) {
        QByteArray line = m_recvBuffer.left(newlineIdx);
        m_recvBuffer.remove(0, newlineIdx + 1);

        QJsonParseError err;
        QJsonDocument doc = QJsonDocument::fromJson(line, &err);
        if (err.error != QJsonParseError::NoError || !doc.isObject()) {
            continue;
        }
        QJsonObject obj = doc.object();
        double predicted = obj.value("predicted_state").toDouble();
        double actual = obj.value("actual_state").toDouble();
        QString verdict = obj.value("verdict").toString();
        qint64 latencyUs = static_cast<qint64>(obj.value("latency_us").toDouble());
        quint64 timestampMs = static_cast<quint64>(obj.value("timestamp_ms").toDouble());

        appendFrame(predicted, actual, verdict, latencyUs, timestampMs);
    }
}

void PhysicsGraphWidget::appendFrame(double predicted, double actual, const QString &verdict,
                                      qint64 latencyUs, quint64 /*timestampMs*/) {
    m_predictedSeries->append(m_xCounter, predicted);
    m_actualSeries->append(m_xCounter, actual);
    m_xCounter += 1.0;

    // Keep only the last N points visible for a scrolling real-time feel.
    if (m_predictedSeries->count() > kMaxVisiblePoints) {
        m_predictedSeries->remove(0);
        m_actualSeries->remove(0);
    }

    double minX = m_predictedSeries->at(0).x();
    double maxX = m_xCounter;
    m_axisX->setRange(minX, maxX);

    // Auto-scale Y to whatever range the physics engine is reporting.
    double lo = std::min(predicted, actual);
    double hi = std::max(predicted, actual);
    if (hi > m_axisY->max()) m_axisY->setMax(hi * 1.1);
    if (lo < m_axisY->min()) m_axisY->setMin(lo * 1.1);

    if (verdict == "CATASTROPHIC") {
        m_statusLabel->setText("<span style='color:#ff5555;font-weight:bold;'>ALARM: command dropped (predicted state unsafe)</span>");
    } else {
        m_statusLabel->setText("<span style='color:#55ff88;'>Nominal — last command cleared</span>");
    }
    m_latencyLabel->setText(QString("Decision latency: %1 us  (budget: 10,000 us)").arg(latencyUs));
}

void PhysicsGraphWidget::onSocketError(QAbstractSocket::SocketError /*error*/) {
    m_statusLabel->setText("Disconnected from VoltGuard engine — retrying...");
}