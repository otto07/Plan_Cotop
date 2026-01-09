import os
import time
import tempfile
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

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


# =============================================================================
# CONFIG STREAMLIT
# =============================================================================
st.set_page_config(
    page_title="Robô ANTT - Consulta Automatizada",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# LOGGING (servidor)
# =============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ANTT_BOT")


# =============================================================================
# CONFIG
# =============================================================================
@dataclass
class Config:
    url_login: str = "https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx"
    timeout_elemento: int = 20

    # Colunas
    col_auto: str = "Auto de Infração"
    col_processo: str = "Nº do Processo"
    col_data: str = "Data da Infração"
    col_codigo: str = "Código da Infração"
    col_fato: str = "Fato Gerador"
    col_andamento: str = "Último Andamento"
    col_data_andamento: str = "Data do Último Andamento"
    col_status: str = "Status Consulta"


CONFIG = Config()
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# SESSION STATE DEFAULTS
# =============================================================================
def init_state():
    defaults = {
        "result_path": None,
        "result_filename": None,
        "run_summary": "",
        "last_run_ok": False,
        "running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# =============================================================================
# SELENIUM DRIVER
# =============================================================================
class WebDriverManager:
    @staticmethod
    def criar_driver(headless: bool = True) -> webdriver.Chrome:
        chrome_options = Options()
        chrome_options.binary_location = "/usr/bin/chromium"

        if headless:
            chrome_options.add_argument("--headless=new")

        # flags essenciais p/ container
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # anti-detecção básica
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(60)
        return driver


# =============================================================================
# LOGIN (baseado no trecho que funciona)
# =============================================================================
class LoginManager:
    def __init__(self, driver: webdriver.Chrome, wait: WebDriverWait, debug: bool):
        self.driver = driver
        self.wait = wait
        self.debug = debug

    def realizar_login(self, usuario: str, senha: str) -> bool:
        status = st.empty()
        try:
            status.info("🌐 Abrindo página de login...")
            self.driver.get(CONFIG.url_login)

            actions = ActionChains(self.driver)

            # 1) usuário
            status.info("👤 Inserindo usuário...")
            id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
            campo_user = self.wait.until(EC.element_to_be_clickable((By.ID, id_user)))
            actions.move_to_element(campo_user).click().perform()
            campo_user.clear()
            campo_user.send_keys(usuario)

            # 2) OK
            status.info("▶️ Confirmando usuário...")
            id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
            self.driver.find_element(By.ID, id_btn_ok).click()

            status.info("⏳ Aguardando sistema...")
            time.sleep(3)

            # 3) senha + ENTER
            status.info("🔒 Inserindo senha...")
            xpath_senha = "//input[@type='password']"
            self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
            campo_senha = self.driver.find_element(By.XPATH, xpath_senha)
            actions.move_to_element(campo_senha).click().perform()
            campo_senha.clear()
            campo_senha.send_keys(senha)
            time.sleep(1)
            campo_senha.send_keys(Keys.RETURN)

            # 4) validação: presença do campo de consulta
            status.info("🔍 Validando acesso...")
            self.wait.until(
                EC.presence_of_element_located(
                    (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                )
            )

            status.empty()
            return True

        except Exception as e:
            status.empty()
            st.error("❌ Erro no login (sem detalhes). Ative o modo debug para ver o erro.")
            if self.debug:
                st.exception(e)
                try:
                    st.image(self.driver.get_screenshot_as_png(), caption="Debug - erro login")
                except Exception:
                    pass
            return False


# =============================================================================
# CONSULTA (baseada no trecho que funciona)
# =============================================================================
class ConsultorANTT:
    def __init__(self, driver: webdriver.Chrome, wait: WebDriverWait, debug: bool):
        self.driver = driver
        self.wait = wait
        self.debug = debug

    def esperar_dados(self, element_id: str, timeout: int = 10) -> str:
        end = time.time() + timeout
        while time.time() < end:
            try:
                val = self.driver.find_element(By.ID, element_id).get_attribute("value")
                if val and val.strip():
                    return val
                time.sleep(0.5)
            except Exception:
                pass
        return ""

    def processar_auto(self, auto: str) -> Dict[str, Any]:
        res = {"status": "erro", "dados": {}, "mensagem": ""}
        janela_main = self.driver.current_window_handle

        try:
            # campo auto
            campo = self.wait.until(
                EC.element_to_be_clickable(
                    (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                )
            )
            campo.clear()
            campo.send_keys(auto)

            encontrou = False
            for _ in range(3):
                try:
                    btn = self.driver.find_element(
                        By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar"
                    )
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)

                    self.wait.until(
                        EC.presence_of_element_located(
                            (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
                        )
                    )
                    encontrou = True
                    break
                except Exception:
                    if "Nenhum registro" in (self.driver.page_source or ""):
                        break

            if not encontrou:
                res["status"] = "nao_encontrado"
                res["mensagem"] = "Auto não localizado"
                return res

            # abre popup
            btn_edit = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0"
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn_edit)

            WebDriverWait(self.driver, 15).until(EC.number_of_windows_to_be(2))
            for w in self.driver.window_handles:
                if w != janela_main:
                    self.driver.switch_to.window(w)
                    break

            time.sleep(3)

            dados = {}
            try:
                id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
                self.wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
                dados["processo"] = self.esperar_dados(id_proc) or self.driver.find_element(By.ID, id_proc).get_attribute("value")

                dados["data_infracao"] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao"
                ).get_attribute("value")

                dados["codigo"] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao"
                ).get_attribute("value")

                dados["fato"] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao"
                ).get_attribute("value")

                try:
                    xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                    self.wait.until(EC.presence_of_element_located((By.XPATH, xp)))
                    tab = self.driver.find_element(By.XPATH, xp)
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

            # fecha popup
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver.switch_to.window(janela_main)
            return res

        except Exception as e:
            res["mensagem"] = f"Erro fluxo: {e}"
            try:
                self.driver.switch_to.window(janela_main)
            except Exception:
                pass
            return res


# =============================================================================
# OUTPUT (arquivo em /tmp para reduzir memória)
# =============================================================================
def salvar_xlsx_em_tmp(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", prefix="antt_result_")
    tmp_path = tmp.name
    tmp.close()

    with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    return tmp_path


# =============================================================================
# PIPELINE PRINCIPAL
# =============================================================================
def executar_pipeline(arquivo_xlsx, usuario: str, senha: str, headless: bool, debug: bool):
    st.session_state.running = True
    st.session_state.last_run_ok = False
    st.session_state.result_path = None
    st.session_state.result_filename = None
    st.session_state.run_summary = ""

    driver = None
    progress = st.progress(0)
    info = st.empty()

    t0 = time.time()

    try:
        df = pd.read_excel(arquivo_xlsx)

        # validação coluna obrigatória
        if CONFIG.col_auto not in df.columns:
            st.error(f"❌ Coluna obrigatória ausente: '{CONFIG.col_auto}'")
            st.session_state.run_summary = "Falha: coluna obrigatória ausente."
            return

        # garante colunas de saída
        for col in [
            CONFIG.col_processo,
            CONFIG.col_data,
            CONFIG.col_codigo,
            CONFIG.col_fato,
            CONFIG.col_andamento,
            CONFIG.col_data_andamento,
            CONFIG.col_status,
        ]:
            if col not in df.columns:
                df[col] = ""

        df = df.astype(object).replace("nan", "").fillna("")
        df_filtrado = df[df[CONFIG.col_auto].astype(str).str.strip() != ""]
        total = int(len(df_filtrado))
        if total == 0:
            st.error("⚠️ Nenhum auto encontrado na planilha.")
            st.session_state.run_summary = "Falha: nenhum auto na planilha."
            return

        info.caption(f"Iniciando: {total} autos.")

        # selenium
        driver = WebDriverManager.criar_driver(headless=headless)
        wait = WebDriverWait(driver, CONFIG.timeout_elemento)

        # login
        if not LoginManager(driver, wait, debug=debug).realizar_login(usuario, senha):
            st.session_state.run_summary = "Falha no login."
            return

        consultor = ConsultorANTT(driver, wait, debug=debug)

        sucesso = 0
        falhas = 0
        # loop (UI leve)
        for i, (original_idx, row) in enumerate(df_filtrado.iterrows(), start=1):
            auto = str(row[CONFIG.col_auto]).strip()
            res = consultor.processar_auto(auto)

            df.at[original_idx, CONFIG.col_status] = res.get("mensagem", "")

            if res.get("status") == "sucesso":
                d = res.get("dados", {})
                df.at[original_idx, CONFIG.col_processo] = d.get("processo", "")
                df.at[original_idx, CONFIG.col_data] = d.get("data_infracao", "")
                df.at[original_idx, CONFIG.col_codigo] = d.get("codigo", "")
                df.at[original_idx, CONFIG.col_fato] = d.get("fato", "")
                df.at[original_idx, CONFIG.col_andamento] = d.get("andamento", "")
                df.at[original_idx, CONFIG.col_data_andamento] = d.get("data_andamento", "")
                sucesso += 1
            else:
                falhas += 1

            # update leve a cada 10 itens (reduz renderização)
            if (i % 10 == 0) or (i == total):
                progress.progress(i / total)
                info.caption(f"Progresso: {i}/{total} | Sucessos: {sucesso} | Falhas/Não encontrados: {falhas}")

            time.sleep(0.3)  # throttle para reduzir risco de bloqueio

        # gera arquivo final em /tmp (mais robusto p/ memória)
        result_path = salvar_xlsx_em_tmp(df)
        result_filename = f"ANTT_Resultado_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"

        st.session_state.result_path = result_path
        st.session_state.result_filename = result_filename
        st.session_state.last_run_ok = True

        dt = int(time.time() - t0)
        st.session_state.run_summary = f"Concluído em ~{dt}s. Sucessos: {sucesso} | Falhas/Não encontrados: {falhas}."

    except Exception as e:
        st.session_state.run_summary = f"Erro no processamento: {e}"
        st.error(st.session_state.run_summary)
        if debug:
            st.exception(e)

    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass

        st.session_state.running = False
        try:
            progress.empty()
            info.empty()
        except Exception:
            pass


# =============================================================================
# UI
# =============================================================================
st.title("🚛 Robô ANTT - Consulta Automatizada (Robusto)")

with st.sidebar:
    st.header("⚙️ Opções")
    debug = st.checkbox("Modo debug (mostrar exceções/screenshot)", value=False)
    # Em Streamlit Cloud, normalmente headless deve ficar sempre ligado
    headless = st.checkbox("Executar headless", value=True)

st.markdown(
    "Este app processa a planilha e mantém o arquivo de saída disponível para download mesmo após reruns do Streamlit, usando `st.session_state` e arquivo temporário."
)

colA, colB = st.columns(2)
with colA:
    usuario = st.text_input("Usuário", disabled=st.session_state.running)
with colB:
    senha = st.text_input("Senha", type="password", disabled=st.session_state.running)

arquivo = st.file_uploader("Planilha (.xlsx) com coluna 'Auto de Infração'", type=["xlsx"], disabled=st.session_state.running)

run = st.button("🚀 Processar", type="primary", use_container_width=True, disabled=st.session_state.running)

if run:
    if not usuario or not senha or arquivo is None:
        st.error("Preencha usuário, senha e selecione a planilha.")
    else:
        executar_pipeline(arquivo, usuario, senha, headless=headless, debug=debug)

# status / resumo
if st.session_state.run_summary:
    if st.session_state.last_run_ok:
        st.success(st.session_state.run_summary)
    else:
        st.warning(st.session_state.run_summary)

# download SEMPRE fora do bloco do processamento (chave robustez)
if st.session_state.result_path and os.path.exists(st.session_state.result_path):
    # Passar arquivo aberto diretamente é suportado (doc). [web:66]
    with open(st.session_state.result_path, "rb") as f:
        st.download_button(
            label="📥 Baixar resultado (XLSX)",
            data=f,
            file_name=st.session_state.result_filename or "ANTT_Resultado.xlsx",
            mime=MIME_XLSX,
            key="download_resultado",
            on_click="ignore",  # evita rerun ao baixar (reduz risco de “reset”). [web:66]
            use_container_width=True,
        )
else:
    st.caption("Nenhum arquivo disponível para download ainda.")
