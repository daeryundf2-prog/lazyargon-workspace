# Velociraptor VQL 아티팩트 수집 템플릿

엔드포인트에 Velociraptor 클라이언트/서버가 **이미 배포되어 있을 때만**
사용한다 (BYO — `python scripts/check_tool.py velociraptor.exe`로 게이트).
VQL은 `velociraptor query` 또는 서버 Notebook에서 실행한다. 결과는 반드시
수집 시각·호스트명·쿼리 원문을 함께 보존한다 (재현성).

## 1. 프로세스 + 메모리 지도

```vql
-- 실행 중인 프로세스의 메모리 맵과 커맨드라인 수집
SELECT Pid, Ppid, Name, CommandLine, Exe,
       MemoryInfo.RSS AS RssBytes,
       create_time AS StartTime
FROM pslist()
```

```vql
-- 특정 PID의 로드 모듈(인젝션 정황 확인)
SELECT Pid, Name, FullPath, BaseAddress, Size
FROM modules(pid=<TARGET_PID>)
```

## 2. 네트워크 연결

```vql
-- 활성 TCP/UDP 연결 + 소유 프로세스 (Windows/macOS 공통)
SELECT Pid, Name, Status,
       Laddr.IP AS LocalIP, Laddr.Port AS LocalPort,
       Raddr.IP AS RemoteIP, Raddr.Port AS RemotePort
FROM netstat()
```

## 3. 브라우저 다운로드 이력 (Chrome 계열)

```vql
-- 다운로드 URL·저장 경로·시각 (SQLite 프로필 직접 질의)
SELECT target_path, tab_url, start_time, end_time,
       total_bytes, received_bytes, danger_type
FROM sqlite(
  file=glob('C:/Users/*/AppData/Local/Google/Chrome/User Data/*/History'),
  query='SELECT target_path, tab_url, start_time, end_time, total_bytes,
                received_bytes, danger_type FROM downloads')
```

## 4. 파일 타임스탬프 일괄 (forensic-audit과 교차검증용)

```vql
-- 디렉터리 트리의 MAC 시각 — OS 표면값, $MFT 분석 대체 아님
SELECT FullPath, Size,
       Mtime AS Modified, Atime AS Accessed,
       Ctime AS Changed, Btime AS Created
FROM glob(globs='C:/Evidence/**')
```

## 주의

- VQL 결과는 `os.stat` 수준의 표면 관측이다 — 타임스탬프 위조 가능성은
  별도 검증. forensic-audit의 "하지 않는 일" 경계를 그대로 따른다.
- 원격 수집 전 반드시 대상 호스트에 대한 수집 권한(위임/동의)을 확인한다.
