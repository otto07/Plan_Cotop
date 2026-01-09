import os
import time
import json
import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

import pandas as pd
import streamlit as st

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import WebDriverException


# =============================================================================
# STREAMLIT
# =============================================================================
st.set_page_config(
    page_title="Robô ANTT - Consulta Automatizada (Robusto)",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ANTT_BOT")

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# CONFIG
# =============================================================================
@dataclass
class Config:
    url_login: str = "https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx"
    timeout: int = 20

    col_auto: str = "Auto de Infração"
    col_processo: str = "Nº do Processo"
    col_data: str = "Data da Infração"
    col_codigo: str = "Código da Infração"
    col_fato: str = "Fato Gerador"
    col_andamento: str = "Último Andamento"
    col_data_andamento: str = "Data do Último Andamento"
    col_status: str = "Status Consulta"


CFG = Config()


# =============================================================================
# SESSION STATE
# =============================================================================
def init_state():
    defaults = {
        "job_id": None,
        "running": False,
        "cursor": 0,
        "total": 0,
        "ok": 0,
        "fail": 0,
        "result_xlsx_path": None,
        "result_xlsx_name": None,
        "summary": "",
        "last_error": "",
        "ui_logs": [],  # lista de (HH:MM:SS, level, msg)
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


def ui_log(msg: str, level: str = "info"):
    ts = time.strftime("%H:%M:%S")
    st.session_state.ui_logs.append((ts, level, msg))
    st.session_state.ui_logs = st.session_state.ui_logs[-120:]


# =============================================================================
# JOB / CHECKPOINT PATHS
# =============================================================================
def make_job_id(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()[:16]


def paths_for_job(job_id: str) -> Dict[str, str]:
    base = f"antt_{job_id}"
    return {
        # >>> TROCA: parquet -> csv.gz (robusto p/ dtype misto)
        "checkpoint_csv": os.path.join("/tmp", f"{base}_checkpoint.csv.gz"),
        "checkpoint_meta": os.path.join("/tmp", f"{base}_meta.json"),
        "result_xlsx": os.path.join("/tmp", f"{base}_result.xlsx"),
    }


def ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in [
        CFG.col_processo,
        CFG.col_data,
        CFG.col_codigo,
        CFG.col_fato,
        CFG.col_andamento,
        CFG.col_data_andamento,
        CFG.col_status,
    ]:
        if col not in df.columns:
            df[col] = ""
    df = df.astype(object).replace("nan", "").fillna("")
    return df


def save_checkpoint(df: pd.DataFrame, meta: Dict[str, Any], job_id: str) -> None:
    """
    Checkpoint robusto:
    - salva CSV gzip (tolerante a dtype misto)
    - não assume tipos numéricos
    """
    p = paths_for_job(job_id)
    df.to_csv(p["checkpoint_csv"], index=False, encoding="utf-8-sig", compression="gzip")
    with open(p["checkpoint_meta"], "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def load_checkpoint(job_id: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict[str, Any]]]:
    p = paths_for_job(job_id)
    if not (os.path.exists(p["checkpoint_csv"]) and os.path.exists(p["checkpoint_meta"])):
        return None, None

    # Lê como string para não quebrar com colunas mistas (ex.: "Peso não encontrado")
    df = pd.read_csv(p["checkpoint_csv"], dtype=str, compression="gzip")
    df = df.astype(object).replace("nan", "").fillna("")

    with open(p["checkpoint_meta"], "r", encoding="utf-8") as f:
        meta = json.load(f)

    return df, meta


def save_result_xlsx(df: pd.DataFrame, job_id: str) -> str:
    p = paths_for_job(job_id)
    with pd.ExcelWriter(p["result_xlsx"], engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return p["result_xlsx"]


# =============================================================================
# SELENIUM RUNTIME (PERSISTE ENTRE RERUNS)
# =============================================================================
class SeleniumRuntime:
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None

    def start(self, headless: bool = True):
        self.stop()

        chrome_options = Options()
        chrome_options.binary_location = "/usr/bin/chromium"
        if headless:
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        service = Service("/usr/bin/chromedriver")
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, CFG.timeout)

    def stop(self):
        try:
            if self.driver is not None:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None
        self.wait = None

    def is_alive(self) -> bool:
        try:
            if self.driver is None:
                return False
            _ = self.driver.current_url
            return True
        except Exception:
            return False


@st.cache_resource
def get_runtime() -> SeleniumRuntime:
    return SeleniumRuntime()


# =============================================================================
# LOGIN / SESSION CHECKS
# =============================================================================
def is_logged_in(rt: SeleniumRuntime) -> bool:
    try:
        if rt.driver is None:
            return False
        rt.driver.find_element(
            By.ID,
            "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao",
        )
        return True
    except Exception:
        return False


def realizar_login(rt: SeleniumRuntime, usuario: str, senha: str, debug: bool) -> bool:
    try:
        ui_log("Abrindo página de login...")
        rt.driver.get(CFG.url_login)

        actions = ActionChains(rt.driver)

        ui_log("Inserindo usuário...")
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = rt.wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        actions.move_to_element(campo_user).click().perform()
        campo_user.clear()
        campo_user.send_keys(usuario)

        ui_log("Confirmando usuário (OK)...")
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        rt.driver.find_element(By.ID, id_btn_ok).click()

        ui_log("Aguardando liberação do campo de senha...")
        time.sleep(3)

        ui_log("Inserindo senha e enviando (ENTER)...")
        xpath_senha = "//input[@type='password']"
        rt.wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
        campo_senha = rt.driver.find_element(By.XPATH, xpath_senha)
        actions.move_to_element(campo_senha).click().perform()
        campo_senha.clear()
        campo_senha.send_keys(senha)
        time.sleep(1)
        campo_senha.send_keys(Keys.RETURN)

        ui_log("Validando acesso (campo de consulta)...")
        rt.wait.until(
            EC.presence_of_element_located(
                (
                    By.ID,
                    "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao",
                )
            )
        )

        ui_log("Login confirmado.")
        return True

    except Exception as e:
        ui_log("Falha no login.", "error")
        if debug:
            st.exception(e)
            try:
                st.image(rt.driver.get_screenshot_as_png(), caption="Debug - falha no login")
            except Exception:
                pass
        return False


def ensure_session(rt: SeleniumRuntime, usuario: str, senha: str, headless: bool, debug: bool) -> bool:
    if not rt.is_alive():
        ui_log("WebDriver não está ativo. Reiniciando driver...", "warning")
        rt.start(headless=headless)

    if is_logged_in(rt):
        return True

    ui_log("Sessão não autenticada. Tentando relogin...", "warning")
    return realizar_login(rt, usuario, senha, debug=debug)


# =============================================================================
# CONSULTA
# =============================================================================
def esperar_dados(rt: SeleniumRuntime, element_id: str, timeout: int = 10) -> str:
    end = time.time() + timeout
    while time.time() < end:
        try:
            val = rt.driver.find_element(By.ID, element_id).get_attribute("value")
            if val and val.strip():
                return val
            time.sleep(0.5)
        except Exception:
            pass
    return ""


def processar_auto(rt: SeleniumRuntime, auto: str) -> Dict[str, Any]:
    res = {"status": "erro", "dados": {}, "mensagem": ""}
    driver = rt.driver
    wait = rt.wait
    janela_main = driver.current_window_handle

    try:
        campo = wait.until(
            EC.element_to_be_clickable(
                (
                    By.ID,
                    "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao",
                )
            )
        )
        campo.clear()
        campo.send_keys(auto)

        encontrou = False
        for _ in range(3):
            try:
                # >>> CORREÇÃO CRÍTICA: NÃO sobrescrever "driver"
                btn = driver.find_element(
                    By.ID,
                    "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar",
                )
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)

                wait.until(
                    EC.presence_of_element_located(
                        (
                            By.ID,
                            "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0",
                        )
                    )
                )
                encontrou = True
                break
            except Exception:
                if "Nenhum registro" in (driver.page_source or ""):
                    break

        if not encontrou:
            res["status"] = "nao_encontrado"
            res["mensagem"] = "Auto não localizado"
            return res

        btn_edit = driver.find_element(
            By.ID,
            "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0",
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)

        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != janela_main:
                driver.switch_to.window(w)
                break
        time.sleep(3)

        dados = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            dados["processo"] = esperar_dados(rt, id_proc) or driver.find_element(By.ID, id_proc).get_attribute("value")

            dados["data_infracao"] = driver.find_element(
                By.ID,
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao",
            ).get_attribute("value")

            dados["codigo"] = driver.find_element(
                By.ID,
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao",
            ).get_attribute("value")

            dados["fato"] = driver.find_element(
                By.ID,
                "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao",
            ).get_attribute("value")

            try:
                xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                wait.until(EC.presence_of_element_located((By.XPATH, xp)))
                tab = driver.find_element(By.XPATH, xp)
                trs = tab.find_elements(By.TAG_NAME, "tr")

                if len(trs) > 1:
                    tds = trs[-1].find_elements(By.TAG_NAME, "td")
                    if len(tds) >= 4:
                        dados["data_andamento"] = tds[3].text
                        dados["andamento"] = tds[1].text
                    elif len(tds) >= 2:
                        dados["data_andamento"] = tds[-1].text
                        dados["andamento"] = tds[0].text
                else:
                    dados["andamento"] = "Sem andamentos"
                    dados["data_andamento"] = ""
            except Exception:
                dados["andamento"] = "Erro Tabela"
                dados["data_andamento"] = ""

            res["status"] = "sucesso"
            res["dados"] = dados
            res["mensagem"] = "Sucesso"

        except Exception as e:
            res["mensagem"] = f"Erro leitura: {e}"

        try:
            driver.close()
        except Exception:
            pass
        driver.switch_to.window(janela_main)
        return res

    except Exception as e:
        res["mensagem"] = f"Erro fluxo: {e}"
        try:
            driver.switch_to.window(janela_main)
        except Exception:
            pass
        return res


def processar_auto_com_recuperacao(
    rt: SeleniumRuntime,
    auto: str,
    usuario: str,
    senha: str,
    headless: bool,
    debug: bool,
    max_retries: int = 2,
) -> Dict[str, Any]:
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            ok = ensure_session(rt, usuario, senha, headless=headless, debug=debug)
            if not ok:
                return {"status": "erro", "dados": {}, "mensagem": "Falha no login/relogin"}

            res = processar_auto(rt, auto)

            if res.get("status") != "sucesso" and not is_logged_in(rt):
                ui_log("Perda de sessão detectada. Forçando reinício do driver...", "warning")
                rt.stop()
                continue

            return res

        except WebDriverException as e:
            last_exc = e
            ui_log(f"Erro WebDriver (tentativa {attempt+1}). Reiniciando driver...", "warning")
            rt.stop()
            time.sleep(1)
            continue
        except Exception as e:
            last_exc = e
            time.sleep(1)
            continue

    return {"status": "erro", "dados": {}, "mensagem": f"Falha após retries: {last_exc}"}


# =============================================================================
# PIPELINE EM LOTES + CHECKPOINT + RERUN
# =============================================================================
def iniciar_job(file_bytes: bytes):
    job_id = make_job_id(file_bytes)
    st.session_state.job_id = job_id

    st.session_state.cursor = 0
    st.session_state.total = 0
    st.session_state.ok = 0
    st.session_state.fail = 0

    st.session_state.result_xlsx_path = None
    st.session_state.result_xlsx_name = None

    st.session_state.summary = ""
    st.session_state.last_error = ""
    st.session_state.ui_logs = []
    ui_log(f"Job iniciado: {job_id}")


def carregar_df_or_checkpoint(uploaded_file) -> pd.DataFrame:
    job_id = st.session_state.job_id

    df_ck, meta = load_checkpoint(job_id)
    if df_ck is not None and meta is not None:
        st.session_state.cursor = int(meta.get("cursor", 0))
        st.session_state.total = int(meta.get("total", len(df_ck)))
        st.session_state.ok = int(meta.get("ok", 0))
        st.session_state.fail = int(meta.get("fail", 0))
        ui_log(f"Checkpoint carregado. Retomando em {st.session_state.cursor}/{st.session_state.total}.")
        return ensure_output_columns(df_ck)

    df = pd.read_excel(uploaded_file)
    if CFG.col_auto not in df.columns:
        raise ValueError(f"Coluna obrigatória ausente: {CFG.col_auto}")
    df = ensure_output_columns(df)

    df_filtrado = df[df[CFG.col_auto].astype(str).str.strip() != ""]
    st.session_state.total = int(len(df_filtrado))
    st.session_state.cursor = 0
    st.session_state.ok = 0
    st.session_state.fail = 0

    ui_log(f"Planilha carregada. Total de autos: {st.session_state.total}.")
    return df


def rodar_lote(
    df: pd.DataFrame,
    usuario: str,
    senha: str,
    headless: bool,
    debug: bool,
    batch_size: int,
    checkpoint_every: int,
    throttle: float,
):
    job_id = st.session_state.job_id
    rt = get_runtime()

    df_filtrado_idx = df[df[CFG.col_auto].astype(str).str.strip() != ""].index.tolist()
    total = len(df_filtrado_idx)
    st.session_state.total = total

    start_cursor = st.session_state.cursor
    end_cursor = min(start_cursor + batch_size, total)
    ui_log(f"Iniciando lote: {start_cursor+1} até {end_cursor} de {total}.")

    progress = st.progress(start_cursor / max(total, 1))
    live = st.empty()

    for pos in range(start_cursor, end_cursor):
        original_idx = df_filtrado_idx[pos]
        auto = str(df.at[original_idx, CFG.col_auto]).strip()

        res = processar_auto_com_recuperacao(
            rt, auto, usuario, senha,
            headless=headless, debug=debug, max_retries=2
        )

        df.at[original_idx, CFG.col_status] = res.get("mensagem", "")

        if res.get("status") == "sucesso":
            d = res.get("dados", {})
            df.at[original_idx, CFG.col_processo] = d.get("processo", "")
            df.at[original_idx, CFG.col_data] = d.get("data_infracao", "")
            df.at[original_idx, CFG.col_codigo] = d.get("codigo", "")
            df.at[original_idx, CFG.col_fato] = d.get("fato", "")
            df.at[original_idx, CFG.col_andamento] = d.get("andamento", "")
            df.at[original_idx, CFG.col_data_andamento] = d.get("data_andamento", "")
            st.session_state.ok += 1
        else:
            st.session_state.fail += 1

        st.session_state.cursor = pos + 1

        if (st.session_state.cursor % 10 == 0) or (st.session_state.cursor == total):
            live.caption(
                f"Progresso: {st.session_state.cursor}/{total} | OK: {st.session_state.ok} | Falhas: {st.session_state.fail}"
            )
            ui_log(f"Progresso: {st.session_state.cursor}/{total} (OK: {st.session_state.ok}, Falhas: {st.session_state.fail}).")

        progress.progress(st.session_state.cursor / max(total, 1))

        # checkpoint + parcial (blindado)
        if (st.session_state.cursor % checkpoint_every == 0) or (st.session_state.cursor == total):
            meta = {
                "cursor": st.session_state.cursor,
                "total": total,
                "ok": st.session_state.ok,
                "fail": st.session_state.fail,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

            try:
                save_checkpoint(df, meta, job_id)
                ui_log(f"Checkpoint salvo em {st.session_state.cursor}/{total}.")
            except Exception as e:
                ui_log(f"Falha ao salvar checkpoint (seguindo execução): {e}", "warning")

            try:
                partial_path = save_result_xlsx(df, job_id)
                st.session_state.result_xlsx_path = partial_path
                st.session_state.result_xlsx_name = f"ANTT_Parcial_{job_id}_{st.session_state.cursor}de{total}.xlsx"
                ui_log("Arquivo parcial atualizado para download.")
            except Exception as e:
                ui_log(f"Falha ao gerar XLSX parcial: {e}", "warning")

        if throttle > 0:
            time.sleep(throttle)

    progress.empty()
    live.empty()

    if st.session_state.cursor >= total:
        ui_log("Processamento finalizado. Gerando arquivo final...")
        try:
            final_path = save_result_xlsx(df, job_id)
            st.session_state.result_xlsx_path = final_path
            st.session_state.result_xlsx_name = f"ANTT_Resultado_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
            ui_log("Arquivo final pronto para download.")
        except Exception as e:
            ui_log(f"Falha ao gerar XLSX final: {e}", "error")

        st.session_state.summary = f"Concluído. OK: {st.session_state.ok} | Falhas/Não encontrados: {st.session_state.fail}"
        st.session_state.running = False
    else:
        st.session_state.summary = f"Em andamento. OK: {st.session_state.ok} | Falhas: {st.session_state.fail}"


# =============================================================================
# UI
# =============================================================================
st.title("Robô ANTT - Consulta Automatizada (Robusto)")

with st.sidebar:
    st.header("Opções")
    debug = st.checkbox("Modo debug (exceções/screenshot)", value=False)
    headless = st.checkbox("Executar headless", value=True)

    batch_size = st.slider("Tamanho do lote", min_value=10, max_value=40, value=20, step=5)
    checkpoint_every = st.slider("Checkpoint a cada N autos", min_value=5, max_value=30, value=10, step=5)
    throttle = st.selectbox("Delay entre consultas", [0.0, 0.2, 0.3, 0.5, 0.8], index=2)

col1, col2 = st.columns(2)
with col1:
    usuario = st.text_input("Usuário", disabled=st.session_state.running)
with col2:
    senha = st.text_input("Senha", type="password", disabled=st.session_state.running)

arquivo = st.file_uploader(
    "Planilha (.xlsx) com coluna 'Auto de Infração'",
    type=["xlsx"],
    disabled=st.session_state.running
)

b1, b2, b3 = st.columns(3)
with b1:
    start = st.button("Iniciar / Retomar", type="primary", use_container_width=True, disabled=st.session_state.running)
with b2:
    stop = st.button("Parar", use_container_width=True, disabled=not st.session_state.running)
with b3:
    reset = st.button("Limpar estado", use_container_width=True)

if reset:
    try:
        get_runtime().stop()
    except Exception:
        pass
    st.session_state.clear()
    init_state()
    st.rerun()

if stop:
    st.session_state.running = False
    ui_log("Execução interrompida pelo usuário.", "warning")
    st.warning("Execução interrompida.")

if start:
    if not usuario or not senha or arquivo is None:
        st.error("Preencha usuário, senha e selecione a planilha.")
    else:
        file_bytes = arquivo.getvalue()
        if not st.session_state.job_id:
            iniciar_job(file_bytes)
        st.session_state.running = True
        ui_log("Execução iniciada.")

# Painel de logs (leve)
with st.status("Execução", expanded=True) as status_box:
    logs = st.session_state.ui_logs[-25:]
    if logs:
        for ts, level, msg in logs:
            if level == "error":
                st.error(f"[{ts}] {msg}")
            elif level == "warning":
                st.warning(f"[{ts}] {msg}")
            else:
                st.write(f"[{ts}] {msg}")
    else:
        st.write("Nenhum log ainda.")

    if st.session_state.running:
        status_box.update(label="Execução (em andamento)", state="running", expanded=True)
    elif st.session_state.last_error:
        status_box.update(label="Execução (com erro)", state="error", expanded=True)
    elif st.session_state.summary:
        status_box.update(label="Execução (finalizada)", state="complete", expanded=False)
    else:
        status_box.update(label="Execução (ociosa)", state="complete", expanded=False)

# Execução em lotes + rerun controlado
if st.session_state.running:
    try:
        df = carregar_df_or_checkpoint(arquivo)
        if st.session_state.total <= 0:
            st.error("Nenhum auto encontrado.")
            st.session_state.running = False
        else:
            rodar_lote(
                df=df,
                usuario=usuario,
                senha=senha,
                headless=headless,
                debug=debug,
                batch_size=int(batch_size),
                checkpoint_every=int(checkpoint_every),
                throttle=float(throttle),
            )

            if st.session_state.running and st.session_state.cursor < st.session_state.total:
                time.sleep(0.2)
                st.rerun()

    except Exception as e:
        st.session_state.running = False
        st.session_state.last_error = str(e)
        ui_log(f"Erro no processamento: {e}", "error")
        st.error(f"Erro no processamento: {e}")
        if debug:
            st.exception(e)

# Resumo
if st.session_state.summary:
    if st.session_state.running:
        st.info(st.session_state.summary)
    else:
        st.success(st.session_state.summary)

# Download sempre disponível (parcial/final)
if st.session_state.result_xlsx_path and os.path.exists(st.session_state.result_xlsx_path):
    with open(st.session_state.result_xlsx_path, "rb") as f:
        st.download_button(
            "Baixar resultado (parcial/final)",
            data=f,
            file_name=st.session_state.result_xlsx_name or "ANTT_Resultado.xlsx",
            mime=MIME_XLSX,
            on_click="ignore",
            use_container_width=True,
            key="download_result",
        )
else:
    st.caption("Nenhum arquivo disponível para download ainda.")
