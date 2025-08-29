# FastAPI 및 요청 관련
from fastapi import FastAPI, Form, Request, Depends, HTTPException, APIRouter
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
    JSONResponse,
    FileResponse,
    Response  # CSV 다운로드용
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# 미들웨어
from starlette.middleware.sessions import SessionMiddleware

# SQLAlchemy ORM
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, text, extract, asc, desc

# DB 모델
from database import get_db
from models.models import Report, ErrorReport, MspReport, LogReport, User, Client

# 유틸리티
from datetime import datetime, timedelta
from math import ceil
from urllib.parse import urlencode
from collections import defaultdict
import io
import csv
import re
import tempfile
from utils.auth import create_access_token, verify_password, get_current_user, get_password_hash
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.exception_handlers import http_exception_handler
from typing import List
from datetime import datetime, time as dt_time


# 외부 라이브러리
from natsort import natsorted
from weasyprint import HTML  # PDF 변환

# 기타
import os  # 필요시 파일 처리용








router = APIRouter()
templates = Jinja2Templates(directory="templates")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="supersecret123")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == HTTP_401_UNAUTHORIZED:
        return templates.TemplateResponse("error/unauthorized.html", {"request": request}, status_code=401)
    return await http_exception_handler(request, exc)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user
    })

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.include_router(router)

@app.get("/", response_class=HTMLResponse)
def main_page(request: Request, db: Session = Depends(get_db)):
    msp_reports = db.query(MspReport).order_by(MspReport.request_date.desc()).limit(5).all()
    error_reports = db.query(ErrorReport).order_by(ErrorReport.error_start_date.desc()).limit(5).all()
    log_reports = db.query(LogReport).order_by(LogReport.log_date.desc()).limit(5).all()
    return templates.TemplateResponse("main.html", {
        "request": request,
        "msp_reports": msp_reports,
        "error_reports": error_reports,
        "log_reports": log_reports
    })

@app.get("/client/options")
def get_client_options(client_name: str, db: Session = Depends(get_db)):
    results = db.query(Client).filter(Client.client_name == client_name).all()
    system_names = sorted({row.system_name for row in results})
    target_envs = sorted({row.target_env for row in results})
    target_components = sorted({row.target_component for row in results if row.target_component})

    return JSONResponse({
        "system_names": system_names,
        "target_envs": target_envs,
        "target_components": target_components
    })

@app.get("/client", response_class=HTMLResponse)
def client_list(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).order_by(Client.client_name).all()
    return templates.TemplateResponse("client/client_list.html", {
        "request": request,
        "clients": clients
    })

@app.post("/client/delete")
def delete_client(
    client_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    client = db.query(Client).filter(Client.client_id == client_id).first()  # ✅ 수정
    if client:
        db.delete(client)
        db.commit()

    return RedirectResponse(url="/client", status_code=303)

# GET: 등록 폼 페이지
@app.get("/client/create", response_class=HTMLResponse)
def client_create_form(request: Request):
    return templates.TemplateResponse("client/client_create.html", {
        "request": request
    })


@app.post("/client/create", response_class=HTMLResponse)
def client_create(
    request: Request,
    db: Session = Depends(get_db),
    client_name: str = Form(...),
    system_name: str = Form(""),
    target_env: str = Form(""),
    cloud_type: str = Form(""),  # ✅ 이 줄 추가!
    target_component: str = Form("")
):
    new_client = Client(
        client_name=client_name,
        system_name=system_name,
        target_env=target_env,
        cloud_type=cloud_type,  # ✅ 모델에 반영
        target_component=target_component
    )
    db.add(new_client)
    db.commit()
    return RedirectResponse(url="/client", status_code=303)



@app.get("/msp", response_class=HTMLResponse)
def msp_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 세션에 저장 (기존대로 유지)
    request.session["name"] = current_user.name
    request.session["username"] = current_user.username

    users = db.query(User).all()
    client_names = db.query(Client.client_name).distinct().all()

    return templates.TemplateResponse("report/msp.html", {
        "request": request,
        "users": users,
        "client_names": [c[0] for c in client_names],
        "current_user_name": current_user.name  # ← 추가
    })



@app.get("/error", response_class=HTMLResponse)
async def error_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 고객사명 목록 조회
    client_names = db.query(Client.client_name).distinct().all()
    return templates.TemplateResponse("report/error.html", {
        "request": request,
        "client_names": [c[0] for c in client_names],
        "current_user_name": current_user.name
    })

@app.get("/log", response_class=HTMLResponse)
async def log_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    client_names = db.query(Client.client_name).distinct().all()

    return templates.TemplateResponse("report/log.html", {
        "request": request,
        "current_user_name": current_user.name,
        "client_names": [c[0] for c in client_names]
    })


# @app.get("/reports", response_class=HTMLResponse)
# def report_list(request: Request, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
#     offset = (page - 1) * limit
#     total = db.query(MspReport).count()
#     total_pages = ceil(total / limit)

#     # 최대 5개의 페이징 번호만 표시
#     start_page = max(1, page - 2)
#     end_page = min(start_page + 4, total_pages)
#     start_page = max(1, end_page - 4)  # 끝 범위로 인해 start_page가 다시 줄어들 수 있음

#     reports = db.query(MspReport)\
#                 .order_by(MspReport.request_date.desc())\
#                 .offset(offset).limit(limit).all()

#     return templates.TemplateResponse("report/report_list.html", {
#         "request": request,
#         "reports": reports,
#         "page": page,
#         "total_pages": total_pages,
#         "start_page": start_page,
#         "end_page": end_page
#     })

# 로그인 폼 페이지
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    # 이미 로그인한 경우 메인 페이지로 리다이렉트
    if request.session.get("username"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login/login.html", {"request": request})

# 로그인 처리
@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse(
            "login/login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 일치하지 않습니다."}
        )

    access_token = create_access_token(data={"sub": user.username})

    response = RedirectResponse(url="/log", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)

    request.session["username"] = user.username
    request.session["name"] = user.name

    return response


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    request.session.clear()
    return response



@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    
    
    return templates.TemplateResponse("login/register.html", {"request": request})



@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    email: str = Form(None),
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        return templates.TemplateResponse("login/register.html", {
            "request": request,
            "error": "이미 존재하는 아이디입니다."
        })

    hashed_pw = get_password_hash(password)  # ✅ 암호화 처리

    new_user = User(
        username=username,
        password=hashed_pw,  # ✅ 해시된 비밀번호 저장
        name=name,
        email=email,
        created_at=datetime.now()
    )
    db.add(new_user)
    db.commit()

    return RedirectResponse(url="/login", status_code=303)


@app.get("/report/{report_id}", response_class=HTMLResponse)
def report_detail_page(request: Request, report_id: int, db: Session = Depends(get_db)):
    report_entry = db.query(Report).filter(Report.report_id == report_id).first()
    if not report_entry:
        raise HTTPException(status_code=404, detail="존재하지 않는 리포트ID입니다.")

    report_type = report_entry.report_type
    if report_type == "msp":
        report = db.query(MspReport).filter(MspReport.report_id == report_id).first()
    elif report_type == "error":
        report = db.query(ErrorReport).filter(ErrorReport.report_id == report_id).first()
    elif report_type == "log":
        report = db.query(LogReport).filter(LogReport.report_id == report_id).first()
    else:
        raise HTTPException(status_code=400, detail="Invalid report type")

    if not report:
        raise HTTPException(status_code=404, detail="Detailed report not found")

    return templates.TemplateResponse("report/report_detail.html", {
        "request": request,
        "report_type": report_type,
        "report": report
    })





@app.post("/msp/submit")
async def submit_msp(
    request: Request,
    manager: str = Form(...),
    request_date: str = Form(...),
    request_time: str = Form(...),
    completed_date: str = Form(None),
    completed_time: str = Form(None),
    client_name: str = Form(...),
    system_name: str = Form(...),
    target_env: str = Form(None),
    cloud_type: str = Form(None),
    requester: str = Form(...),
    request_type: str = Form(...),
    request_content: str = Form(None),
    purpose: str = Form(None),
    response: str = Form(None),
    etc: str = Form(None),
    status: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ✅ 현재 로그인 사용자 가져오기
):
    request_datetime = datetime.strptime(f"{request_date} {request_time}", "%Y-%m-%d %H:%M")
    completed_datetime = None
    if completed_date and completed_time:
        completed_datetime = datetime.strptime(f"{completed_date} {completed_time}", "%Y-%m-%d %H:%M")

    # Report 등록
    report = Report(
        create_by=current_user.user_id,  # ✅ user_id 직접 참조
        report_type="msp",
        created_at=datetime.now()
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # MspReport 등록
    msp_report = MspReport(
        report_id=report.report_id,
        manager=manager,
        request_date=request_datetime,
        completed_date=completed_datetime,
        client_name=client_name,
        system_name=system_name,
        target_env=target_env,
        cloud_type=cloud_type,
        requester=requester,
        request_type=request_type,
        request_content=request_content,
        purpose=purpose,
        response=response,
        etc=etc,
        status=status
    )
    db.add(msp_report)
    db.commit()

    return RedirectResponse(url="/msp", status_code=303)



@app.post("/error/submit")
async def submit_error(
    request: Request,
    manager: str = Form(...),
    status: str = Form(None),
    error_start_date: str = Form(...),
    start_time: str = Form(...),
    error_end_date: str = Form(None),
    end_time: str = Form(None),
    client_name: str = Form(...),
    system_name: str = Form(...),
    target_env: str = Form(None),
    cloud_type: str = Form(None),
    target_component: str = Form(None),
    customer_impact: str = Form(None),
    error_info: str = Form(...),
    error_reason: str = Form(None),
    action_taken: str = Form(None),
    etc: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ✅ 추가
):
    report = Report(
        create_by=current_user.user_id,  # ✅ 세션 → JWT 기반 사용자 ID
        report_type="error",
        created_at=datetime.now()
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    error_start_dt = datetime.strptime(f"{error_start_date} {start_time}", "%Y-%m-%d %H:%M") if error_start_date and start_time else None
    error_end_dt = datetime.strptime(f"{error_end_date} {end_time}", "%Y-%m-%d %H:%M") if error_end_date and end_time else None

    error_report = ErrorReport(
        report_id=report.report_id,
        manager=manager,
        status=status,
        error_start_date=error_start_dt,
        error_end_date=error_end_dt,
        client_name=client_name,
        system_name=system_name,
        target_env=target_env,
        cloud_type=cloud_type,
        target_component=target_component,
        customer_impact=customer_impact,
        error_info=error_info,
        error_reason=error_reason,
        action_taken=action_taken,
        etc=etc
    )
    db.add(error_report)
    db.commit()

    return RedirectResponse(url="/error_reports", status_code=303)

@app.get("/error/components")
def get_target_components(db: Session = Depends(get_db)):
    # 중복 제거 + NULL 제외
    results = db.query(ErrorReport.target_component).distinct().all()
    components = [r[0] for r in results if r[0] is not None]
    return JSONResponse(content={"components": components})



@app.post("/log/submit")
async def submit_log(
    request: Request,
    log_date: str = Form(...),
    log_time: str = Form(...),
    client_name: str = Form(...),
    system_name: str = Form(...),
    target_env: str = Form(None),
    cloud_type: str = Form(None),
    log_type: str = Form(None),
    # log_type: str = Form(...),
    content: str = Form(None),
    action: str = Form(None),
    manager: str = Form(...),
    status: str = Form(None),
    completed_date: str = Form(None),
    completed_time: str = Form(None),
    summary: str = Form(None),
    etc: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    log_datetime = datetime.strptime(f"{log_date} {log_time}", "%Y-%m-%d %H:%M")
    completed_datetime = None
    if completed_date and completed_time:
        completed_datetime = datetime.strptime(f"{completed_date} {completed_time}", "%Y-%m-%d %H:%M")

    report = Report(
        create_by=current_user.user_id,
        report_type="log",
        created_at=datetime.now()
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    log_report = LogReport(
        report_id=report.report_id,
        log_date=log_datetime,
        client_name=client_name,
        system_name=system_name,
        target_env=target_env,
        cloud_type=cloud_type,
        log_type=log_type,
        content=content,
        action=action,
        manager=manager,
        status=status,
        completed_date=completed_datetime,
        summary=summary,
        etc=etc
    )
    db.add(log_report)
    db.commit()

    return RedirectResponse(url="/log_reports", status_code=303)







# @app.get("/error_reports", response_class=HTMLResponse)
# def error_report_list(request: Request, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
#     offset = (page - 1) * limit
#     total = db.query(ErrorReport).count()
#     total_pages = ceil(total / limit)

#     # 최대 5개의 페이징 번호만 표시
#     start_page = max(1, page - 2)
#     end_page = min(start_page + 4, total_pages)
#     start_page = max(1, end_page - 4)

#     reports = db.query(ErrorReport)\
#                 .order_by(ErrorReport.error_start_date.desc())\
#                 .offset(offset).limit(limit).all()

#     return templates.TemplateResponse("report/error_report_list.html", {
#         "request": request,
#         "reports": reports,
#         "page": page,
#         "total_pages": total_pages,
#         "start_page": start_page,
#         "end_page": end_page
#     })


# @app.get("/log_reports", response_class=HTMLResponse)
# def log_report_list(request: Request, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
#     offset = (page - 1) * limit
#     total = db.query(LogReport).count()
#     total_pages = ceil(total / limit)

#     # 최대 5개의 페이징 번호만 표시
#     start_page = max(1, page - 2)
#     end_page = min(start_page + 4, total_pages)
#     start_page = max(1, end_page - 4)

#     reports = db.query(LogReport).order_by(LogReport.log_date.desc()).offset(offset).limit(limit).all()

#     return templates.TemplateResponse("report/log_reports.html", {
#         "request": request,
#         "reports": reports,
#         "page": page,
#         "total_pages": total_pages,
#         "start_page": start_page,
#         "end_page": end_page
#     })


@app.get("/reports/download")
async def download_msp_csv(
    start_date: str = "",
    end_date: str = "",
    manager: str = "",
    requester: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    request_type: str = "",
    search: str = "",
    db: Session = Depends(get_db)
):
    query = db.query(MspReport)

    if manager:
        query = query.filter(MspReport.manager.contains(manager))
    if requester:
        query = query.filter(MspReport.requester.contains(requester))
    if status:
        query = query.filter(MspReport.status == status)
    if client_name:
        query = query.filter(MspReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(MspReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(MspReport.target_env.contains(target_env))
    if request_type:
        query = query.filter(MspReport.request_type.contains(request_type))
    if start_date and end_date:
        query = query.filter(
            MspReport.request_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )
    if search:
        query = query.filter(
            MspReport.client_name.contains(search) |
            MspReport.system_name.contains(search) |
            MspReport.manager.contains(search)
        )

    # ✅ 최신 요청일자 기준 내림차순 정렬 추가
    query = query.order_by(MspReport.request_date.desc())

    reports = query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "요청일자", "고객사", "시스템명", "대상 환경",
        "요청자", "요청유형", "요청내용", "참고사항",
        "담당자", "상태", "완료일자", "답변내용", "비고"
    ])

    for r in reports:
        writer.writerow([
            r.request_date.strftime("%Y-%m-%d %H:%M") if r.request_date else '',
            r.client_name or '',
            r.system_name or '',
            r.target_env or '',
            r.requester or '',
            r.request_type or '',
            r.request_content or '',
            r.purpose or '',
            r.manager or '',
            r.status or '',
            r.completed_date.strftime("%Y-%m-%d %H:%M") if r.completed_date else '',
            r.response or '',
            r.etc or ''
        ])

    output.seek(0)
    bom = '\ufeff'
    return Response(
        content=bom + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=msp_reports.csv"}
    )






@app.get("/error_reports/download")
async def download_error_csv(
    start_date: str = "",
    end_date: str = "",
    manager: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    target_component: str = "",
    search: str = "",
    db: Session = Depends(get_db)
):
    query = db.query(ErrorReport)

    if manager:
        query = query.filter(ErrorReport.manager.contains(manager))
    if status:
        query = query.filter(ErrorReport.status == status)
    if client_name:
        query = query.filter(ErrorReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(ErrorReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(ErrorReport.target_env.contains(target_env))
    if target_component:
        query = query.filter(ErrorReport.target_component.contains(target_component))
    if start_date and end_date:
        query = query.filter(
            ErrorReport.error_start_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )
    if search:
        query = query.filter(
            ErrorReport.client_name.contains(search) |
            ErrorReport.system_name.contains(search) |
            ErrorReport.manager.contains(search)
        )

    # ✅ 최신 장애일자 기준 정렬 추가
    query = query.order_by(ErrorReport.error_start_date.desc())

    reports = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "장애일자", "고객사", "시스템명", "대상 환경", "장애대상", "고객 영향",
        "장애내용", "장애원인", "조치내용", "담당자", "상태", "장애종료일자", "비고"
    ])

    for r in reports:
        writer.writerow([
            r.error_start_date.strftime("%Y-%m-%d %H:%M") if r.error_start_date else '',
            r.client_name or '',
            r.system_name or '',
            r.target_env or '',
            r.target_component or '',
            r.customer_impact or '',
            r.error_info or '',
            r.error_reason or '',
            r.action_taken or '',
            r.manager or '',
            r.status or '',
            r.error_end_date.strftime("%Y-%m-%d %H:%M") if r.error_end_date else '',
            r.etc or ''
        ])

    output.seek(0)
    bom = '\ufeff'
    return Response(
        content=bom + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=error_reports.csv"}
    )







@app.get("/log_reports/download")
async def download_log_csv(
    start_date: str = "",
    end_date: str = "",
    manager: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    log_type: str = "",
    search: str = "",
    db: Session = Depends(get_db)
):
    query = db.query(LogReport)

    if manager:
        query = query.filter(LogReport.manager.contains(manager))
    if status:
        query = query.filter(LogReport.status == status)
    if client_name:
        query = query.filter(LogReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(LogReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(LogReport.target_env.contains(target_env))
    if log_type:
        query = query.filter(LogReport.log_type.contains(log_type))
    if start_date and end_date:
        query = query.filter(
            LogReport.log_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )
    if search:
        query = query.filter(
            LogReport.client_name.contains(search) |
            LogReport.system_name.contains(search) |
            LogReport.manager.contains(search)
        )

    # ✅ 최신 일자 기준 정렬 추가
    query = query.order_by(LogReport.log_date.desc())

    reports = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "일자", "고객사", "시스템명", "대상 환경", "유형",
        "내용", "조치", "담당자", "상태", "완료일자", "요약", "비고"
    ])

    for r in reports:
        writer.writerow([
            r.log_date.strftime("%Y-%m-%d %H:%M") if r.log_date else '',
            r.client_name or '',
            r.system_name or '',
            r.target_env or '',
            r.log_type or '',
            r.content or '',
            r.action or '',
            r.manager or '',
            r.status or '',
            r.completed_date.strftime("%Y-%m-%d %H:%M") if r.completed_date else '',
            r.summary or '',
            r.etc or ''
        ])

    output.seek(0)
    bom = '\ufeff'
    return Response(
        content=bom + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=log_reports.csv"}
    )


@app.get("/report/{report_id}/edit")
async def edit_report_form(request: Request, report_id: int, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    report_type = report.report_type
    detail = None

    if report_type == "msp":
        detail = db.query(MspReport).filter(MspReport.report_id == report_id).first()
    elif report_type == "error":
        detail = db.query(ErrorReport).filter(ErrorReport.report_id == report_id).first()
    elif report_type == "log":
        detail = db.query(LogReport).filter(LogReport.report_id == report_id).first()
    else:
        raise HTTPException(status_code=400, detail="알 수 없는 리포트 유형입니다.")

    if not detail:
        raise HTTPException(status_code=404, detail="상세 리포트를 찾을 수 없습니다.")

    return templates.TemplateResponse("report/report_edit.html", {
        "request": request,
        "report": detail,
        "report_type": report_type
    })


# 수정 저장 처리
@app.post("/report/{report_id}/edit")
async def report_edit(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    # form 데이터는 동적으로 받기 위해 request.form() 직접 파싱할 거야
):
    form = await request.form()
    report_entry = db.query(Report).filter(Report.report_id == report_id).first()
    if not report_entry:
        raise HTTPException(status_code=404, detail="Report not found")

    report_type = report_entry.report_type

    if report_type == "msp":
        report = db.query(MspReport).filter(MspReport.report_id == report_id).first()
        if report:
            report.manager = form.get("manager")
            report.status = form.get("status")
            report.request_date = datetime.strptime(form.get("request_date") + " " + form.get("request_time"), "%Y-%m-%d %H:%M")
            completed_date = form.get("completed_date")
            completed_time = form.get("completed_time")
            if completed_date and completed_time:
                report.completed_date = datetime.strptime(completed_date + " " + completed_time, "%Y-%m-%d %H:%M")
            else:
                report.completed_date = None
            report.client_name = form.get("client_name")
            report.system_name = form.get("system_name")
            report.target_env = form.get("target_env")
            report.requester = form.get("requester")
            report.request_type = form.get("request_type")
            report.request_content = form.get("request_content")
            report.purpose = form.get("purpose")
            report.response = form.get("response")
            report.etc = form.get("etc")
    elif report_type == "error":
        report = db.query(ErrorReport).filter(ErrorReport.report_id == report_id).first()
        if report:
            report.manager = form.get("manager")
            report.status = form.get("status")
            report.error_start_date = datetime.strptime(form.get("error_start_date") + " " + form.get("start_time"), "%Y-%m-%d %H:%M")
            error_end_date = form.get("error_end_date")
            end_time = form.get("end_time")
            if error_end_date and end_time:
                report.error_end_date = datetime.strptime(error_end_date + " " + end_time, "%Y-%m-%d %H:%M")
            else:
                report.error_end_date = None
            report.client_name = form.get("client_name")
            report.system_name = form.get("system_name")
            report.target_env = form.get("target_env")
            report.target_component = form.get("target_component")
            report.customer_impact = form.get("customer_impact")
            report.error_info = form.get("error_info")
            report.error_reason = form.get("error_reason")
            report.action_taken = form.get("action_taken")
            report.etc = form.get("etc")
    elif report_type == "log":
        report = db.query(LogReport).filter(LogReport.report_id == report_id).first()
        if report:
            report.manager = form.get("manager")
            report.status = form.get("status")
            report.log_date = datetime.strptime(form.get("log_date") + " " + form.get("log_time"), "%Y-%m-%d %H:%M")
            completed_date = form.get("completed_date")
            completed_time = form.get("completed_time")
            if completed_date and completed_time:
                report.completed_date = datetime.strptime(completed_date + " " + completed_time, "%Y-%m-%d %H:%M")
            else:
                report.completed_date = None
            report.client_name = form.get("client_name")
            report.system_name = form.get("system_name")
            report.target_env = form.get("target_env")
            report.log_type = form.get("log_type")
            report.content = form.get("content")
            report.action = form.get("action")
            report.summary = form.get("summary")
            report.etc = form.get("etc")

    db.commit()

    return RedirectResponse(url=f"/report/{report_id}", status_code=303)




# 삭제 처리
@app.post("/report/{report_id}/delete")
async def report_delete(report_id: int, db: Session = Depends(get_db)):
    report_entry = db.query(Report).filter(Report.report_id == report_id).first()
    if not report_entry:
        raise HTTPException(status_code=404, detail="Report not found")

    report_type = report_entry.report_type

    # 세부 테이블 먼저 삭제
    if report_type == "msp":
        db.query(MspReport).filter(MspReport.report_id == report_id).delete()
    elif report_type == "error":
        db.query(ErrorReport).filter(ErrorReport.report_id == report_id).delete()
    elif report_type == "log":
        db.query(LogReport).filter(LogReport.report_id == report_id).delete()

    # 그 다음 report 테이블 삭제
    db.delete(report_entry)
    db.commit()

    # 삭제 후 목록으로 이동
    if report_type == "msp":
        return RedirectResponse(url="/reports", status_code=303)
    elif report_type == "error":
        return RedirectResponse(url="/error_reports", status_code=303)
    elif report_type == "log":
        return RedirectResponse(url="/log_reports", status_code=303)

from sqlalchemy import asc, desc  # 추가

def natural_keys(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', text)]

@app.get("/reports", response_class=HTMLResponse)
def report_list(
    request: Request,
    page: int = 1,
    limit: int = 10,
    manager: str = "",
    requester: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    request_type: str = "",
    start_date: str = "",
    end_date: str = "",
    search: str = "",
    sort: str = "request_date",
    direction: str = "desc",
    db: Session = Depends(get_db)
):
    offset = (page - 1) * limit
    query = db.query(MspReport)

    if requester:
        query = query.filter(MspReport.requester.contains(requester))
    if manager:
        query = query.filter(MspReport.manager.contains(manager))
    if status:
        query = query.filter(MspReport.status == status)
    if client_name:
        query = query.filter(MspReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(MspReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(MspReport.target_env.contains(target_env))
    if request_type:
        query = query.filter(MspReport.request_type.contains(request_type))
    if start_date and end_date:
        query = query.filter(
            MspReport.request_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )
        

    # ✅ 통합검색: 여러 필드에 OR 조건으로 적용
    from sqlalchemy import or_
    if search:
        keyword = f"%{search}%"
        query = query.filter(
            or_(
                MspReport.client_name.like(keyword),
                MspReport.system_name.like(keyword),
                MspReport.manager.like(keyword),
                MspReport.requester.like(keyword),
                MspReport.request_type.like(keyword),
                MspReport.request_content.like(keyword),
                MspReport.purpose.like(keyword),
                MspReport.response.like(keyword),
                MspReport.etc.like(keyword),
                MspReport.status.like(keyword)
            )
        )

    all_reports = query.all()

    # 자연 정렬
    natural_sort_fields = ["client_name", "system_name", "manager", "request_type", "status", "requester"]
    if sort in natural_sort_fields:
        all_reports.sort(key=lambda x: natural_keys(getattr(x, sort) or ""), reverse=(direction == "desc"))
    elif hasattr(MspReport, sort):
        all_reports.sort(key=lambda x: getattr(x, sort), reverse=(direction == "desc"))

    total = len(all_reports)
    total_pages = ceil(total / limit)
    start_page = max(1, page - 2)
    end_page = min(start_page + 4, total_pages)
    start_page = max(1, end_page - 4)

    reports = all_reports[offset:offset + limit]

    query_dict = {
        "manager": manager,
        "requester": requester,
        "status": status,
        "client_name": client_name,
        "system_name": system_name,
        "requester": requester,
        "target_env": target_env,
        "request_type": request_type,
        "start_date": start_date,
        "end_date": end_date,
        "search": search,
        "sort": sort,
        "direction": direction
    }
    filtered_query = {k: v for k, v in query_dict.items() if v}
    query_string = urlencode(filtered_query)

    return templates.TemplateResponse("report/report_list.html", {
        "request": request,
        "reports": reports,
        "page": page,
        "total_pages": total_pages,
        "start_page": start_page,
        "end_page": end_page,
        "query_string": query_string,
        "current_sort": sort,
        "current_direction": direction
    })






@app.get("/error_reports", response_class=HTMLResponse)
def error_report_list(
    request: Request,
    page: int = 1,
    limit: int = 10,
    manager: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    target_component: str = "",
    start_date: str = "",
    end_date: str = "",
    search: str = "",
    sort: str = "error_start_date",
    direction: str = "desc",
    db: Session = Depends(get_db),
    
):
    offset = (page - 1) * limit
    query = db.query(ErrorReport)

    if manager:
        query = query.filter(ErrorReport.manager.contains(manager))
    if status:
        query = query.filter(ErrorReport.status == status)
    if client_name:
        query = query.filter(ErrorReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(ErrorReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(ErrorReport.target_env.contains(target_env))
    if target_component:
        query = query.filter(ErrorReport.target_component.contains(target_component))
    if start_date and end_date:
        query = query.filter(
            ErrorReport.error_start_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )

    # ✅ 통합검색
    from sqlalchemy import or_
    if search:
        keyword = f"%{search}%"
        query = query.filter(
            or_(
                ErrorReport.client_name.like(keyword),
                ErrorReport.system_name.like(keyword),
                ErrorReport.manager.like(keyword),
                ErrorReport.status.like(keyword),
                ErrorReport.target_env.like(keyword),
                ErrorReport.target_component.like(keyword),
                ErrorReport.customer_impact.like(keyword),
                ErrorReport.error_info.like(keyword),
                ErrorReport.error_reason.like(keyword),
                ErrorReport.action_taken.like(keyword),
                ErrorReport.etc.like(keyword)
            )
        )

    all_reports = query.all()
    if sort in ["client_name", "system_name", "manager"]:
        all_reports.sort(key=lambda x: natural_keys(getattr(x, sort) or ""), reverse=(direction == "desc"))
    elif hasattr(ErrorReport, sort):
        all_reports.sort(key=lambda x: getattr(x, sort), reverse=(direction == "desc"))

    total = len(all_reports)
    total_pages = ceil(total / limit)
    start_page = max(1, page - 2)
    end_page = min(start_page + 4, total_pages)
    start_page = max(1, end_page - 4)

    reports = all_reports[offset:offset + limit]

    query_dict = {
        "manager": manager,
        "status": status,
        "client_name": client_name,
        "system_name": system_name,
        "target_env": target_env,
        "target_component": target_component,
        "start_date": start_date,
        "end_date": end_date,
        "search": search,
        "sort": sort,
        "direction": direction
    }
    query_string = urlencode({k: v for k, v in query_dict.items() if v})

    return templates.TemplateResponse("report/error_report_list.html", {
        "request": request,
        "reports": reports,
        "page": page,
        "total_pages": total_pages,
        "start_page": start_page,
        "end_page": end_page,
        "query_string": query_string,
        "current_sort": sort,
        "current_direction": direction
    })





@app.get("/log_reports", response_class=HTMLResponse)
def log_report_list(
    request: Request,
    page: int = 1,
    limit: int = 10,
    manager: str = "",
    status: str = "",
    client_name: str = "",
    system_name: str = "",
    target_env: str = "",
    log_type: str = "",
    start_date: str = "",
    end_date: str = "",
    search: str = "",
    sort: str = "log_date",
    direction: str = "desc",
    db: Session = Depends(get_db)
):
    offset = (page - 1) * limit
    query = db.query(LogReport)

    if manager:
        query = query.filter(LogReport.manager.contains(manager))
    if status:
        query = query.filter(LogReport.status == status)
    if client_name:
        query = query.filter(LogReport.client_name.contains(client_name))
    if system_name:
        query = query.filter(LogReport.system_name.contains(system_name))
    if target_env:
        query = query.filter(LogReport.target_env.contains(target_env))
    if log_type:
        query = query.filter(LogReport.log_type.contains(log_type))
    if start_date and end_date:
        query = query.filter(
            LogReport.log_date.between(start_date + " 00:00:00", end_date + " 23:59:59")
        )

    # ✅ 통합검색
    from sqlalchemy import or_
    if search:
        keyword = f"%{search}%"
        query = query.filter(
            or_(
                LogReport.client_name.like(keyword),
                LogReport.system_name.like(keyword),
                LogReport.manager.like(keyword),
                LogReport.status.like(keyword),
                LogReport.target_env.like(keyword),
                LogReport.log_type.like(keyword),
                LogReport.content.like(keyword),
                LogReport.action.like(keyword),
                LogReport.summary.like(keyword),
                LogReport.etc.like(keyword)
            )
        )

    all_reports = query.all()
    if sort in ["client_name", "system_name", "manager"]:
        all_reports.sort(key=lambda x: natural_keys(getattr(x, sort) or ""), reverse=(direction == "desc"))
    elif hasattr(LogReport, sort):
        all_reports.sort(key=lambda x: getattr(x, sort), reverse=(direction == "desc"))

    total = len(all_reports)
    total_pages = ceil(total / limit)
    start_page = max(1, page - 2)
    end_page = min(start_page + 4, total_pages)
    start_page = max(1, end_page - 4)

    reports = all_reports[offset:offset + limit]

    query_dict = {
        "manager": manager,
        "status": status,
        "client_name": client_name,
        "system_name": system_name,
        "target_env": target_env,
        "log_type": log_type,
        "start_date": start_date,
        "end_date": end_date,
        "search": search,
        "sort": sort,
        "direction": direction
    }
    query_string = urlencode({k: v for k, v in query_dict.items() if v})

    return templates.TemplateResponse("report/log_reports.html", {
        "request": request,
        "reports": reports,
        "page": page,
        "total_pages": total_pages,
        "start_page": start_page,
        "end_page": end_page,
        "query_string": query_string,
        "current_sort": sort,
        "current_direction": direction
    })



@app.get("/admin/users", response_class=HTMLResponse)
def user_management_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    users = db.query(User).all()
    return templates.TemplateResponse("admin/user_list.html", {
        "request": request,
        "users": users
    })


@app.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def edit_user_page(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse("admin/user_edit.html", {
        "request": request,
        "user": user
    })



@app.post("/admin/users/{user_id}/edit")
async def update_user_info(
    user_id: int,
    username: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.username = username
    user.name = name
    user.email = email
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)



@app.post("/admin/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)




@app.get("/profile", response_class=HTMLResponse)
async def profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse("user/profile.html", {
        "request": request,
        "user": current_user
    })


@app.get("/change_password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse("user/change_password.html", {
        "request": request,
        "error": None
    })


@app.post("/change_password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 🔐 bcrypt 해시 비교
    if not verify_password(current_password, current_user.password):
        return templates.TemplateResponse("user/change_password.html", {
            "request": request,
            "error": "현재 비밀번호가 일치하지 않습니다."
        })

    if new_password != confirm_password:
        return templates.TemplateResponse("user/change_password.html", {
            "request": request,
            "error": "새 비밀번호가 일치하지 않습니다."
        })

    # 🔐 bcrypt 해시로 저장
    current_user.password = get_password_hash(new_password)
    db.commit()

    return RedirectResponse(url="/", status_code=303)


@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats(request: Request, db: Session = Depends(get_db)):
    user = Depends(get_current_user)
    if user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    total_reports = db.query(Report).count()
    last_7_days = datetime.today() - timedelta(days=7)
    last_30_days = datetime.today() - timedelta(days=30)
    recent_7 = db.query(Report).filter(Report.created_at >= last_7_days).count()
    recent_30 = db.query(Report).filter(Report.created_at >= last_30_days).count()

    # 상태 분포
    status_counts = defaultdict(int)
    for model in [MspReport, ErrorReport, LogReport]:
        for row in db.query(model.status).all():
            status_counts[row[0]] += 1

    # 기업별 리포트 개수
    client_summary = defaultdict(lambda: {"msp": 0, "error": 0, "log": 0})
    for row in db.query(MspReport.client_name).all():
        client_summary[row[0]]["msp"] += 1
    for row in db.query(ErrorReport.client_name).all():
        client_summary[row[0]]["error"] += 1
    for row in db.query(LogReport.client_name).all():
        client_summary[row[0]]["log"] += 1

    # 담당자별 처리 현황
    manager_counts = defaultdict(lambda: {"count": 0, "done": 0})
    for model in [MspReport, ErrorReport, LogReport]:
        for row in db.query(model.manager, model.status).all():
            manager_counts[row[0]]["count"] += 1
            if row[1] == "완료":
                manager_counts[row[0]]["done"] += 1

    # 시스템별 리포트 수
    system_counts = defaultdict(int)
    for model in [MspReport, ErrorReport, LogReport]:
        for row in db.query(model.system_name).all():
            system_counts[row[0]] += 1

    # 장애 대상별 장애 건수
    component_counts = defaultdict(int)
    for row in db.query(ErrorReport.target_component).all():
        if row[0]:
            component_counts[row[0]] += 1

    # ✅ 월별 리포트 수
    from sqlalchemy import extract, func
    monthly_counts = defaultdict(lambda: {"msp": 0, "error": 0, "log": 0})

    for year, month, count in db.query(
        extract('year', MspReport.request_date),
        extract('month', MspReport.request_date),
        func.count()
    ).group_by(
        extract('year', MspReport.request_date),
        extract('month', MspReport.request_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["msp"] += count

    for year, month, count in db.query(
        extract('year', ErrorReport.error_start_date),
        extract('month', ErrorReport.error_start_date),
        func.count()
    ).group_by(
        extract('year', ErrorReport.error_start_date),
        extract('month', ErrorReport.error_start_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["error"] += count

    for year, month, count in db.query(
        extract('year', LogReport.log_date),
        extract('month', LogReport.log_date),
        func.count()
    ).group_by(
        extract('year', LogReport.log_date),
        extract('month', LogReport.log_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["log"] += count

    return templates.TemplateResponse("admin/stats.html", {
        "request": request,
        "total_reports": total_reports,
        "recent_7": recent_7,
        "recent_30": recent_30,
        "status_counts": dict(status_counts),
        "client_summary": dict(client_summary),
        "manager_counts": dict(manager_counts),
        "system_counts": dict(system_counts),
        "monthly_counts": dict(sorted(monthly_counts.items())),
        "component_counts": dict(component_counts)  # ✅ 장애대상별 건수 추가
    })


@app.get("/admin/stats/client", response_class=HTMLResponse)
def client_stats_list(request: Request, db: Session = Depends(get_db)):
    user = Depends(get_current_user)
    if user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    # msp, error, log 리포트에서 고객사 목록 추출
    msp_clients = db.query(MspReport.client_name).distinct().all()
    error_clients = db.query(ErrorReport.client_name).distinct().all()
    log_clients = db.query(LogReport.client_name).distinct().all()

    # set으로 중복 제거 후 정렬
    clients = sorted(set(row[0] for row in (msp_clients + error_clients + log_clients) if row[0]))

    return templates.TemplateResponse("admin/client_list.html", {
        "request": request,
        "clients": clients
    })

@app.get("/admin/stats/client/{client_name}", response_class=HTMLResponse)
def client_stats_detail(client_name: str, request: Request, db: Session = Depends(get_db)):
    user = Depends(get_current_user)
    if user.username != "admin":
        return RedirectResponse(url="/login", status_code=303)

    # 리포트 수
    msp_count = db.query(MspReport).filter(MspReport.client_name == client_name).count()
    error_count = db.query(ErrorReport).filter(ErrorReport.client_name == client_name).count()
    log_count = db.query(LogReport).filter(LogReport.client_name == client_name).count()
    total = msp_count + error_count + log_count

    # 상태 분포
    status_counts = defaultdict(int)
    for model in [MspReport, ErrorReport, LogReport]:
        for row in db.query(model.status).filter(model.client_name == client_name).all():
            status_counts[row[0]] += 1

    # 시스템별 분포
    system_counts = defaultdict(int)
    for model in [MspReport, ErrorReport, LogReport]:
        for row in db.query(model.system_name).filter(model.client_name == client_name).all():
            system_counts[row[0]] += 1

    # 장애 대상별 분포 (ErrorReport만)
    component_counts = defaultdict(int)
    for row in db.query(ErrorReport.target_component).filter(ErrorReport.client_name == client_name).all():
        if row[0]:
            component_counts[row[0]] += 1

    # 월별 리포트 수
    from sqlalchemy import extract, func
    monthly_counts = defaultdict(lambda: {"msp": 0, "error": 0, "log": 0})

    for year, month, count in db.query(
        extract('year', MspReport.request_date),
        extract('month', MspReport.request_date),
        func.count()
    ).filter(MspReport.client_name == client_name).group_by(
        extract('year', MspReport.request_date),
        extract('month', MspReport.request_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["msp"] += count

    for year, month, count in db.query(
        extract('year', ErrorReport.error_start_date),
        extract('month', ErrorReport.error_start_date),
        func.count()
    ).filter(ErrorReport.client_name == client_name).group_by(
        extract('year', ErrorReport.error_start_date),
        extract('month', ErrorReport.error_start_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["error"] += count

    for year, month, count in db.query(
        extract('year', LogReport.log_date),
        extract('month', LogReport.log_date),
        func.count()
    ).filter(LogReport.client_name == client_name).group_by(
        extract('year', LogReport.log_date),
        extract('month', LogReport.log_date)
    ).all():
        key = f"{int(year):04d}-{int(month):02d}"
        monthly_counts[key]["log"] += count

    return templates.TemplateResponse("admin/client_stats.html", {
        "request": request,
        "client_name": client_name,
        "msp_count": msp_count,
        "error_count": error_count,
        "log_count": log_count,
        "total": total,
        "status_counts": dict(status_counts),
        "system_counts": dict(system_counts),
        "component_counts": dict(component_counts),
        "monthly_counts": dict(sorted(monthly_counts.items()))
    })




# @app.get("/admin/stats/client/{client_name}/pdf")
# def download_client_pdf(client_name: str, request: Request, db: Session = Depends(get_db)):
#     user = Depends(get_current_user)
# if user.username != "admin":
#         return RedirectResponse(url="/login", status_code=303)

#     # 기존 로직과 동일하게 데이터 수집
#     msp_count = db.query(MspReport).filter(MspReport.client_name == client_name).count()
#     error_count = db.query(ErrorReport).filter(ErrorReport.client_name == client_name).count()
#     log_count = db.query(LogReport).filter(LogReport.client_name == client_name).count()
#     total = msp_count + error_count + log_count

#     status_counts = defaultdict(int)
#     for model in [MspReport, ErrorReport, LogReport]:
#         for row in db.query(model.status).filter(model.client_name == client_name).all():
#             status_counts[row[0]] += 1

#     system_counts = defaultdict(int)
#     for model in [MspReport, ErrorReport, LogReport]:
#         for row in db.query(model.system_name).filter(model.client_name == client_name).all():
#             system_counts[row[0]] += 1

#     component_counts = defaultdict(int)
#     for row in db.query(ErrorReport.target_component).filter(ErrorReport.client_name == client_name).all():
#         if row[0]:
#             component_counts[row[0]] += 1

#     from sqlalchemy import extract
#     monthly_counts = defaultdict(lambda: {"msp": 0, "error": 0, "log": 0})

#     for year, month, count in db.query(
#         extract('year', MspReport.request_date),
#         extract('month', MspReport.request_date),
#         func.count()
#     ).filter(MspReport.client_name == client_name).group_by(
#         extract('year', MspReport.request_date),
#         extract('month', MspReport.request_date)
#     ).all():
#         key = f"{int(year):04d}-{int(month):02d}"
#         monthly_counts[key]["msp"] += count

#     for year, month, count in db.query(
#         extract('year', ErrorReport.error_start_date),
#         extract('month', ErrorReport.error_start_date),
#         func.count()
#     ).filter(ErrorReport.client_name == client_name).group_by(
#         extract('year', ErrorReport.error_start_date),
#         extract('month', ErrorReport.error_start_date)
#     ).all():
#         key = f"{int(year):04d}-{int(month):02d}"
#         monthly_counts[key]["error"] += count

#     for year, month, count in db.query(
#         extract('year', LogReport.log_date),
#         extract('month', LogReport.log_date),
#         func.count()
#     ).filter(LogReport.client_name == client_name).group_by(
#         extract('year', LogReport.log_date),
#         extract('month', LogReport.log_date)
#     ).all():
#         key = f"{int(year):04d}-{int(month):02d}"
#         monthly_counts[key]["log"] += count

#     # HTML 렌더링 → PDF
#     html_content = templates.get_template("admin/client_stats.html").render({
#         "request": request,
#         "client_name": client_name,
#         "msp_count": msp_count,
#         "error_count": error_count,
#         "log_count": log_count,
#         "total": total,
#         "status_counts": dict(status_counts),
#         "system_counts": dict(system_counts),
#         "component_counts": dict(component_counts),
#         "monthly_counts": dict(sorted(monthly_counts.items()))
#     })

#     with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
#         HTML(string=html_content, base_url="http://localhost:8000/static").write_pdf(tmp_file.name) # 운영시 변경 필요
#         return FileResponse(tmp_file.name, filename=f"{client_name}_통계.pdf", media_type="application/pdf")
# 


# ------------------------------------------------------------------
# 솔리데오 옵션: 고객사 / (고객사 선택 시) 시스템/환경 목록
# ------------------------------------------------------------------
@app.get("/solideo/options", response_class=JSONResponse)
def solideo_options(client: str = "", db: Session = Depends(get_db)):
    """
    - client 미지정: 고객사 목록 반환
    - client 지정: 해당 고객사의 시스템/환경 목록 반환
    """
    if not client:
        clients = set()
        for cls in (MspReport, ErrorReport, LogReport):
            # .all() 결과는 튜플(값,) 이므로 c[0] 형태
            for c in db.query(cls.client_name).distinct().all():
                if c[0]:
                    clients.add(c[0].strip())
        # 자연 정렬
        return JSONResponse({"clients": natsorted(clients), "systems": [], "envs": []})

    # 특정 고객사일 때
    systems, envs = set(), set()

    for cls in (MspReport, ErrorReport, LogReport):
        for s in (
            db.query(cls.system_name)
              .filter(cls.client_name == client)
              .distinct()
              .all()
        ):
            if s[0]:
                systems.add(s[0].strip())
        for e in (
            db.query(cls.target_env)
              .filter(cls.client_name == client)
              .distinct()
              .all()
        ):
            if e[0]:
                envs.add(e[0].strip())

    return JSONResponse({
        "clients": [],
        "systems": natsorted(systems),
        "envs": natsorted(envs),
    })


# ------------------------------------------------------------------
# 작성 폼
# ------------------------------------------------------------------
@app.get("/solideo/report", response_class=HTMLResponse)
def solideo_new_form(request: Request):
    return templates.TemplateResponse("solideo/solideo_report.html", {
        "request": request
    })


# ------------------------------------------------------------------
# 제출
# ------------------------------------------------------------------
@app.post("/solideo/report/submit")
def solideo_submit(
    request: Request,
    manager: str = Form(...),
    date: str = Form(...),                   # YYYY-MM-DD
    time_slot: List[str] = Form(None),       # 체크박스 복수 선택(없을 수도 있음)
    client_name: str = Form(""),
    system_name: str = Form(""),
    target_env: str = Form(""),
    content: str = Form(...),
    summary: str = Form(...),
    special_note: str = Form(""),
    db: Session = Depends(get_db)
):
    # --- 필수 검증 ---
    if not manager.strip():
        raise HTTPException(status_code=400, detail="담당자는 필수입니다.")
    if not date.strip():
        raise HTTPException(status_code=400, detail="일자는 필수입니다.")
    if time_slot is None or len(time_slot) == 0:
        raise HTTPException(status_code=400, detail="시간대는 최소 1개 이상 선택하세요.")
    if not content.strip():
        raise HTTPException(status_code=400, detail="업무 내용은 필수입니다.")
    if not summary.strip():
        raise HTTPException(status_code=400, detail="참고사항은 필수입니다.")

    # --- 날짜 파싱(자정으로 고정) ---
    try:
        d = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        log_dt = datetime.combine(d, dt_time(0, 0, 0))
    except ValueError:
        raise HTTPException(status_code=400, detail="일자 형식이 잘못되었습니다(YYYY-MM-DD).")

    # --- 시간대 문자열로 합치기 (예: '오전,오후') ---
    # 체크박스가 1개면 문자열로 들어올 가능성을 대비
    if isinstance(time_slot, str):
        time_slot_list = [time_slot]
    else:
        time_slot_list = [t for t in time_slot if t and t.strip()]
    time_slot_str = ",".join(time_slot_list)

    # --- 저장 ---
    item = LogReport(
        log_date=log_dt,
        client_name=(client_name.strip() or None),
        system_name=(system_name.strip() or None),
        target_env=(target_env.strip() or None),
        log_type="SOLIDEO",
        content=content.strip(),
        action=(special_note.strip() or None),   # 특이사항 -> action
        manager=manager.strip(),
        status="작성",
        summary=summary.strip(),
        etc=time_slot_str                          # 체크박스 선택값 보관
    )
    db.add(item)
    db.commit()

    return RedirectResponse(url="/", status_code=303)


# 대체 휴가 신청
# 고객사/시스템/환경 옵션 (기존 리포트에서 distinct 추출)
@app.get("/leave/options", response_class=JSONResponse)
def leave_options(client: str = "", db: Session = Depends(get_db)):
    clients, systems, envs = set(), set(), set()
    if not client:
        for cls in (MspReport, ErrorReport, LogReport):
            for c in db.query(cls.client_name).distinct():
                if c[0]: clients.add(c[0])
        return JSONResponse({"clients": sorted(clients), "systems": [], "envs": []})

    for cls in (MspReport, ErrorReport, LogReport):
        for s in db.query(cls.system_name).filter(cls.client_name == client).distinct():
            if s[0]: systems.add(s[0])
        for e in db.query(cls.target_env).filter(cls.client_name == client).distinct():
            if e[0]: envs.add(e[0])
    return JSONResponse({"clients": [], "systems": sorted(systems), "envs": sorted(envs)})

# 폼 보기
@app.get("/leave/comp/new", response_class=HTMLResponse)
def leave_comp_form(request: Request):
    return templates.TemplateResponse("leave/comp_form.html", {"request": request})

# 제출
@app.post("/leave/comp/submit")
def leave_comp_submit(
    request: Request,
    manager: str = Form(...),
    start_date: str = Form(...),   # YYYY-MM-DD
    start_time: str = Form(...),   # HH:MM
    end_date: str = Form(...),     # YYYY-MM-DD
    end_time: str = Form(...),     # HH:MM
    client_name: str = Form(""),
    system_name: str = Form(""),
    target_env: str = Form(""),
    reason: str = Form(...),       # 신청 사유
    memo: str = Form(""),          # 인수인계/메모 (옵션)
    db: Session = Depends(get_db)
):
    # 유효성 검사
    for fid, val in {
        "담당자": manager, "시작일자": start_date, "시작시간": start_time,
        "완료일자": end_date, "완료시간": end_time, "신청 사유": reason
    }.items():
        if not str(val).strip():
            raise HTTPException(status_code=400, detail=f"{fid}은(는) 필수입니다.")

    # 날짜시간 결합
    try:
        start_dt = datetime.strptime(start_date.strip()+" "+start_time.strip(), "%Y-%m-%d %H:%M")
        end_dt   = datetime.strptime(end_date.strip()+" "+end_time.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜/시간 형식이 올바르지 않습니다.")

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="완료일시가 시작일시 이후여야 합니다.")

    # 저장 매핑 (새 컬럼 추가 없이 운영)
    item = LogReport(
        log_date=start_dt,            # 시작일시
        completed_date=end_dt,        # 완료일시
        client_name=client_name or None,
        system_name=system_name or None,
        target_env=target_env or None,
        manager=manager.strip(),
        log_type="LEAVE",             # 구분자
        status="신청",
        content=reason.strip(),       # 신청 사유
        summary="대체휴가 신청",        # 간단 라벨
        action=(memo.strip() or None),
        etc=f"start_time={start_time.strip()},end_time={end_time.strip()}"
    )
    db.add(item)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

app.mount("/static", StaticFiles(directory="static"), name="static")
