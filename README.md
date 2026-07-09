# Equipment Automation

시험 장비를 자동으로 제어하고 측정 결과를 저장하는 Python 기반 통합 시험 자동화 프로그램입니다.

Tkinter GUI에서 장비 주소, 시험 조건, 저장 폴더를 입력하면 Recorder를 중심으로 온도 데이터를 수집하고, 연결된 장비 구성에 따라 Power Supply와 Power Meter를 함께 사용해 시험을 진행합니다.

## 프로젝트 개요

기존 프로그램은 `automation.py` 한 파일에 GUI, 장비 연결, 명령 전송, 측정, CSV 저장 코드가 모두 들어 있었습니다. CVCF는 `Series6000`, Recorder는 `GP20` 중심으로 동작했고, 모든 장비가 연결되어 있어야 한다는 전제에 가까운 구조였습니다.

현재 코드는 장비 제어와 시험 실행 흐름을 분리해 유지보수하기 쉽게 정리했고, 장비 일부가 없어도 가능한 범위에서 시험을 진행할 수 있도록 개선했습니다.

또한 기존에 시험 진행 후 USB를 사용해 데이터를 PC로 옮기고 universal viewer를 이용해 직접 PDF로 생성하던 과정까지 자동화하였습니다.

## 주요 개선 내용

- `automation.py`에 모여 있던 코드를 역할별로 분리
- CVCF, Recorder, Power Meter를 장비별 드라이버 구조로 모듈화
- 시험 조건 모델과 시험 실행 로직을 `test_models.py`, `test_runner.py`로 분리
- Recorder를 필수 장비로 두고, CVCF와 Power Meter는 선택적으로 사용 가능하게 개선
- Power Supply가 없어도 전압 변경 없이 현재 조건에서 온도 측정 가능
- Power Meter가 없어도 온도 중심 시험과 CSV 저장 가능
- AC/DC 출력 모드 선택 추가
- DC 모드에서는 주파수 입력을 사용하지 않도록 처리
- GP20 외 MV2000 Recorder 지원 추가
- Series6000 외 PCR 계열 CVCF 지원 추가
- Recorder에서 생성된 `GEV`, `DAE` 파일 자동 다운로드
- 다운로드 된 `GEV`, `DAE` 파일 PDF로 자동 생성

## 지원 장비

- CVCF: Series6000, PCR 계열
- Recorder: GP20, MV2000
- Power Meter: WT310

Recorder는 장비마다 채널 규칙이 달라서 각 드라이버에서 따로 처리합니다.

- GP20: 기존 100번대 블록별 01~10 채널 규칙
- MV2000: `001~048` 연속 채널 규칙

## 시험 실행 기능

현재 프로그램은 입력된 조건에 따라 시험을 자동 실행하고 결과를 CSV로 저장하고 recorder 장비에 생성된 `GEV`, `DAE` 파일 자동 다운로드 후 결과 PDF를 생성합니다.

- 전압/주파수 조건 조합 생성
- AC/DC 모드에 따른 CVCF 제어
- Recorder 녹화 시작/정지 자동 처리
- Recorder 온도 데이터 주기적 수집
- Power Meter 연결 시 전압, 전류, 전력, 주파수 측정
- 시험 조건 사이 대기 시간 처리
- 시험 종료 후 새로 생성된 Recorder 원본 파일 다운로드
- 다운로드된 원본 파일을 universal_viewer로 자동 PDF 변환

## 추가 통합 예정 기능

아래 기능들은 별도 코드나 로직으로 준비되어 있으며, 현재 프로젝트 코드에 통합할 예정입니다.

- 온도 포화 상태 판정
- 포화되지 않은 경우 일정 시간 후 재확인
- Universal Viewer를 이용한 Recorder 원본 파일 PDF 변환

## 프로젝트 구조

```text
.
├── automation.py              # Tkinter GUI 및 전체 실행 흐름
├── test_models.py             # 시험 조건/계획 데이터 모델
├── test_runner.py             # 시험 실행 및 CSV 저장
└── devices/
    ├── cvcf/                  # CVCF 장비 드라이버
    ├── recorder/              # Recorder 장비 드라이버 및 FTP 다운로드
    └── power_meter/           # Power Meter 장비 드라이버
```

## 핵심 개선점

기존 단일 파일 장비 제어 코드를 유지보수 가능한 모듈 구조로 분리했고, 모든 장비가 있어야만 동작하던 흐름을 Recorder 중심의 유연한 시험 구조로 개선했습니다. 또한 원본 파일을 옮기고 PDF를 직접 생성하던 과정을 자동화하였습니다.
