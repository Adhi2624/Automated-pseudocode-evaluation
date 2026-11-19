"""HTML pages. Access control is enforced by the JSON API the pages call."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def welcome(request: Request):
    return render(request, "welcome.html")


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return render(request, "login.html")


@router.get("/tests", response_class=HTMLResponse)
async def tests_list(request: Request):
    return render(request, "tests.html")


@router.get("/tests/{tid}", response_class=HTMLResponse)
async def test_page(request: Request, tid: str):
    return render(request, "test.html")


@router.get("/thank", response_class=HTMLResponse)
async def thank(request: Request):
    return render(request, "thank.html")


@router.get("/staff/login", response_class=HTMLResponse)
async def staff_login(request: Request):
    return render(request, "staff_login.html")


@router.get("/staff", response_class=HTMLResponse)
async def staff(request: Request):
    return render(request, "staff.html")
