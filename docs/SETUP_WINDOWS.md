# Windows 설치 가이드

Python이나 터미널에 익숙하지 않아도 이 가이드를 따라하면 실행할 수 있습니다.

---

## Step 1: 프로젝트 폴더 열기

파일 탐색기에서 프로젝트 폴더를 연 뒤, 빈 곳을 **Shift + 우클릭** →
"여기에서 터미널 열기" 또는 "여기에서 PowerShell 열기"를 선택합니다.

또는 터미널에서 직접 이동:

```
cd C:\path\to\x-posting-system
```

---

## Step 2: 가상환경 만들기

```bash
python -m venv venv
```

> `python`이 인식되지 않으면 전체 경로로 실행하세요:
> ```
> "C:\Users\<사용자명>\AppData\Local\Python\bin\python.exe" -m venv venv
> ```

---

## Step 3: 가상환경 활성화

```bash
# PowerShell
.\venv\Scripts\Activate.ps1

# CMD (명령 프롬프트)
.\venv\Scripts\activate.bat

# Git Bash
source venv/Scripts/activate
```

활성화되면 터미널 앞에 `(venv)` 가 표시됩니다.

> **PowerShell 실행 정책 오류가 나는 경우:**
> ```
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> 를 실행한 뒤 다시 활성화하세요.

---

## Step 4: 패키지 설치

```bash
pip install -r requirements.txt
```

`Successfully installed ...` 메시지가 나오면 완료입니다.

---

## Step 5: 환경변수 파일 생성

```bash
# PowerShell
Copy-Item .env.example .env

# CMD
copy .env.example .env
```

`.env` 파일을 메모장으로 열어 API 키를 입력합니다:

```bash
notepad .env
```

> **중요: `.env` 파일은 절대 GitHub에 올리면 안 됩니다.**
> `.gitignore`에 이미 등록되어 있으나, 직접 확인하세요.

API 키 상세 설명 → [ENV_GUIDE.md](ENV_GUIDE.md)

---

## Step 6: 실행

```bash
python run.py
```

성공하면:
- FastAPI 서버: http://localhost:8000
- API 문서: http://localhost:8000/docs
- 텔레그램 봇 자동 시작 (토큰이 있는 경우)

---

## Step 7: 파이프라인 테스트 (API 키 없이)

```bash
python scripts/ingest_sample.py
```

한국 출산율·반도체 샘플 기사를 입력하고 Mock AI로 전체 파이프라인을 실행합니다.
결과는 http://localhost:8000/drafts/pending 에서 확인할 수 있습니다.

---

## 자주 발생하는 오류

### `python` 명령이 안 될 때 (Microsoft Store가 열리는 경우)

```bash
"C:\Users\<사용자명>\AppData\Local\Python\bin\python.exe" run.py
```

### `ModuleNotFoundError: No module named 'app'`

프로젝트 루트 폴더에서 실행하고 있는지 확인하세요:

```bash
cd C:\path\to\x-posting-system
python run.py
```

### `pip install` 실패

가상환경이 활성화된 상태인지 확인 후 재시도:

```bash
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 텔레그램 봇이 응답하지 않을 때

1. `.env`의 `TELEGRAM_BOT_TOKEN` 과 `TELEGRAM_CHAT_ID` 값을 확인합니다
2. Chat ID를 모르면:
   ```bash
   python scripts/get_telegram_chat_id.py
   ```
3. 텔레그램에서 봇에게 먼저 `/start` 메시지를 보낸 뒤 다시 시도하세요

---

## GitHub에 안전하게 올리기

### 올리면 안 되는 파일

| 파일 | 이유 |
|------|------|
| `.env` | API 키 포함 |
| `*.db` | 개인 데이터 포함 |
| `*.log` | 내부 로그 |

`.gitignore`에 이미 등록되어 있습니다.

### 저장소 생성 및 푸시

```bash
# GitHub CLI가 있는 경우 (권장)
gh repo create x-posting-system --private --source=. --push

# GitHub CLI가 없는 경우
# 1. https://github.com/new 에서 Private 저장소 생성
# 2. 아래 명령 실행 (YOUR_USERNAME을 본인 ID로 변경)
git remote add origin https://github.com/YOUR_USERNAME/x-posting-system.git
git branch -M main
git push -u origin main
```

### 변경사항 커밋

```bash
git add -A
git commit -m "변경 내용 설명"
git push
```
