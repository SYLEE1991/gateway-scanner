# Windows Network Bridge App

Windows 시스템 트레이 앱으로, 특정 장치가 연결되면 자동으로 이더넷 IP를 설정하고 WiFi와 네트워크 브릿지를 생성합니다.

## 요구사항

- Windows 10/11
- Python 3.10+
- 관리자 권한 (네트워크 설정 변경에 필요)

## 설치

```bash
cd windows-bridge-app
pip install -r requirements.txt
```

## 사용법

```bash
python main.py
```

앱이 관리자 권한 없이 실행되면 자동으로 UAC 승격을 요청합니다.

## 설정

`config.json`을 직접 편집하거나, 시스템 트레이 아이콘 우클릭 → "Open Settings"으로 GUI에서 설정할 수 있습니다.

### 주요 설정 항목

| 항목 | 설명 |
|------|------|
| `target_device.hardware_id` | 감지할 장치의 하드웨어 ID (예: `USB\VID_1234&PID_5678`) |
| `target_device.detection_method` | 감지 방식: `hardware_id` 또는 `friendly_name` |
| `ethernet_adapter.name` | 이더넷 어댑터 이름 (예: `Ethernet`) |
| `ethernet_adapter.static_ip` | 설정할 고정 IP |
| `wifi_adapter.name` | WiFi 어댑터 이름 (예: `Wi-Fi`) |
| `bridge.auto_create` | 장치 연결 시 자동 브릿지 생성 여부 |

### 장치 Hardware ID 확인 방법

1. 장치 관리자 열기 (devmgmt.msc)
2. 대상 장치 우클릭 → 속성 → 세부 정보
3. "하드웨어 ID" 선택 후 값 복사
4. 또는 앱 설정 GUI에서 "Scan USB Devices" 버튼 사용

## 동작 방식

1. **장치 감지**: WMI를 통해 주기적으로 대상 장치 존재 여부를 폴링
2. **장치 연결 시**:
   - 이더넷 어댑터에 고정 IP/DNS 설정 (netsh)
   - WiFi ↔ 이더넷 네트워크 브릿지 생성 (PowerShell)
   - 브릿지 실패 시 ICS(인터넷 연결 공유)로 폴백
3. **장치 분리 시**:
   - 브릿지 제거
   - 이더넷 어댑터를 DHCP로 복원

## 시스템 트레이 메뉴

- **Open Settings**: 설정 GUI 열기
- **Force Bridge Now**: 수동으로 브릿지 생성
- **Remove Bridge**: 브릿지 제거
- **Revert to DHCP**: 이더넷을 DHCP로 복원
- **Exit**: 앱 종료 (브릿지 자동 정리)

## 트레이 아이콘 색상

- 회색: 유휴
- 파란색: 모니터링 중
- 초록색: 브릿지 활성
- 빨간색: 오류 발생
