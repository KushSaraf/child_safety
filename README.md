# Tiny Traces - Child Safety Monitoring System

![Tiny Traces Logo](https://img.shields.io/badge/Tiny%20Traces-Child%20Safety-blue?style=for-the-badge&logo=shield)

A comprehensive child safety monitoring system that combines BLE (Bluetooth Low Energy) tracking, real-time alerts, and AI-powered CCTV recognition to help parents keep their children safe.

## 🌟 Features

### For Parents
- **Real-time Device Monitoring**: Track your child's BLE device with live signal strength monitoring
- **Parent Dashboard**: Comprehensive dashboard with device status, alerts, and signal charts
- **Affordable Pricing**: Super affordable device at just ₹500 with promotional offers
- **User Registration**: Easy registration and device purchase system
- **Alert System**: Instant notifications when device goes out of range

### For Administrators
- **Admin Dashboard**: Complete system overview with statistics and analytics
- **User Management**: Monitor registered parents and active devices
- **System Health**: Real-time monitoring of BLE, database, and API status
- **Multiple Admin Roles**: Super Admin, Organizer, and Support access levels

### Technical Features
- **BLE Tracking**: Bluetooth Low Energy device monitoring with RSSI analysis
- **CCTV Integration**: AI-powered child detection using YOLOv8 model
- **Missing Children Database**: Analysis of missing children patterns and statistics
- **Real-time Analytics**: Live charts and data visualization
- **Responsive Design**: Works on desktop, tablet, and mobile devices

## 🏗️ System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   ESP32 Tag     │    │   Flask Web App  │    │   Admin Panel   │
│   (BLE Device)  │◄──►│   (Python)       │◄──►│   (Dashboard)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │   YOLOv8 Model   │
                       │   (CCTV Demo)    │
                       └──────────────────┘
```

## 📁 Project Structure

```
child_safety/
├── flask_app.py                    # Main Flask web application
├── requirements.txt                # Python dependencies
├── users.json                      # User database (JSON)
├── missing_children_dataset_10000.csv  # Missing children data
├── ble_scanner.py                  # BLE device scanning module
├── rssi_analyzer.py                # RSSI signal analysis
├── esp32_tag/
│   └── child_tag.ino              # ESP32 BLE beacon code
└── model/
    ├── cctv_simulation.py         # CCTV demo simulation
    ├── yolov8n.pt                 # YOLOv8 model weights
    ├── result.mp4                 # Demo video output
    ├── data/                      # Training dataset
    │   ├── train/                 # Training images & labels
    │   ├── valid/                 # Validation images & labels
    │   └── test/                  # Test images & labels
    └── runs/                      # Training results
        ├── detect/                # Detection results
        └── train/                 # Training logs
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- ESP32 development board (for hardware testing)
- Modern web browser

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd child_safety
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Flask application**
   ```bash
   python flask_app.py
   ```

4. **Access the application**
   - Open your browser and go to `http://localhost:5000`
   - The application will start with BLE monitoring in the background

### ESP32 Setup (Optional)

1. **Install Arduino IDE** with ESP32 support
2. **Open** `esp32_tag/child_tag.ino`
3. **Configure** the `TAG_NAME` constant with your device name
4. **Upload** to your ESP32 board
5. **Power on** the device to start BLE broadcasting

## 🔧 Configuration

### BLE Scanner Configuration

The BLE scanner can be configured in `ble_scanner.py`:

```python
# RSSI threshold for alerts (dBm)
RSSI_THRESHOLD = -80

# Scanning window size
WINDOW_SIZE = 10

# Device name to track
DEVICE_NAME = "Child-01"
```

### Flask App Configuration

Key configuration in `flask_app.py`:

```python
# Secret key for sessions (change in production!)
app.secret_key = 'your-secret-key-change-this-in-production'

# File paths
CSV_PATH = "missing_children_dataset_10000.csv"
VIDEO_PATH = "model/result.mp4"
USERS_DB_PATH = "users.json"
```

## 👥 User Accounts

### Demo Accounts

#### Parent Account
- **Email**: `demo@tinytraces.com`
- **Password**: `demo123`

#### Admin Accounts
- **Super Admin**: `admin@tinytraces.com` / `admin123`
- **Organizer**: `organizer@tinytraces.com` / `org123`
- **Support**: `support@tinytraces.com` / `support123`

## 📱 Usage Guide

### For Parents

1. **Register**: Visit `/register` to create an account and purchase a device
2. **Login**: Use `/login` to access your dashboard
3. **Monitor**: View real-time device status and signal strength
4. **Alerts**: Receive notifications when device goes out of range

### For Administrators

1. **Login**: Visit `/admin-login` to access admin panel
2. **Dashboard**: View system statistics and health status
3. **Manage**: Monitor users, devices, and system alerts
4. **Reports**: Generate system reports and analytics

## 🔍 API Endpoints

### Public Endpoints
- `GET /` - Main dashboard
- `GET /insights` - Analytics dashboard
- `GET /cctv` - CCTV demo page
- `GET /register` - Parent registration
- `GET /login` - Parent login
- `GET /admin-login` - Admin login

### Protected Endpoints
- `GET /parent-dashboard` - Parent monitoring dashboard
- `GET /admin-dashboard` - Admin management dashboard

### API Endpoints
- `GET /api/stats` - System statistics
- `GET /api/rssi` - BLE/RSSI status
- `POST /api/alert` - Create alert log entry

## 🛠️ Development

### Adding New Features

1. **Backend**: Add new routes in `flask_app.py`
2. **Frontend**: Update HTML templates with new UI components
3. **Database**: Modify user storage in `users.json` or add new data files
4. **BLE**: Extend functionality in `ble_scanner.py` or `rssi_analyzer.py`

### Testing

1. **BLE Testing**: Use ESP32 with the provided Arduino code
2. **Web Testing**: Access different user accounts and test all features
3. **Admin Testing**: Test admin functions with demo admin accounts

## 🔒 Security Considerations

- **Change Secret Key**: Update `app.secret_key` in production
- **HTTPS**: Use HTTPS in production environments
- **Database Security**: Implement proper database security for user data
- **Input Validation**: Add comprehensive input validation
- **Rate Limiting**: Implement rate limiting for API endpoints

## 📊 Data Analysis

The system includes analysis of missing children data with:
- Recovery rate statistics
- Geographic distribution
- Age and demographic analysis
- Time-based trends
- Circumstance analysis

## 🎯 Future Enhancements

- [ ] Mobile app for parents
- [ ] GPS integration for outdoor tracking
- [ ] SMS/Email alert system
- [ ] Advanced AI models for behavior analysis
- [ ] Integration with emergency services
- [ ] Multi-language support
- [ ] Payment gateway integration

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For support and questions:
- Create an issue in the repository
- Contact the development team
- Check the documentation

## 🙏 Acknowledgments

- ESP32 BLE library for device communication
- YOLOv8 for computer vision capabilities
- Flask framework for web application
- Bootstrap for responsive UI design
- Chart.js for data visualization

---

**Tiny Traces** - Keeping children safe, one trace at a time. 👶🛡️
