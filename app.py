import streamlit as st
import pandas as pd
import time
import logging
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Any

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

# =============================================================================
# CONFIGURAÇÕES DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Robô ANTT - Cloud Pro", 
    page_icon="🚛", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# CONFIGURAÇÕES GLOBAIS
# =============================================================================
@dataclass
class Config:
    """Configurações centralizadas da aplicação"""
    url_login: str = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
    timeout_elemento: int = 20
    
    # Colunas da Planilha
    col_auto: str = 'Auto de Infração'
    col_processo: str = 'Nº do Processo'
    col_data: str = 'Data da Infração'
    col_codigo: str = 'Código da Infração'
    col_fato: str = 'Fato Gerador'
    col_andamento: str = 'Último Andamento'
    col_data_andamento: str = 'Data do Último Andamento'
    col_status: str = 'Status Consulta'

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("ANTT_Bot")

# Modo Debug Global
DEBUG_MODE = st.sidebar.checkbox("🐛 Modo Debug (Screenshots)", value=False)

# =============================================================================
# GERENCIADOR DE DRIVER
# =============================================================================
class WebDriverManager:
    """Gerencia criação e configuração do Chrome WebDriver"""
    
    @staticmethod
    def criar_driver(headless: bool = True):
        chrome_options = Options()
        chrome_options.binary_location = "/usr/bin/chromium"
        
        if headless:
            chrome_options.add_argument("--headless=new")
        
        # Flags essenciais
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Anti-detecção básica
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except Exception as e:
            st.error(f"❌ Erro ao iniciar navegador: {e}")
            st.stop()

# =============================================================================
# LÓGICA DE LOGIN (BASEADA NO SEU SCRIPT FUNCIONAL)
# =============================================================================
class LoginManager:
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config

    def realizar_login(self, usuario: str, senha: str) -> bool:
        """Implementação exata da lógica fornecida pelo usuário"""
        status = st.empty()
        
        try:
            status.info("🌐 Acessando sistema...")
            self.driver.get(self.config.url_login)
            
            # ActionChains é vital aqui
            actions = ActionChains(self.driver)

            # 1. Usuário
            status.info("👤 Inserindo usuário...")
            id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
            
            campo_user = self.wait.until(EC.element_to_be_clickable((By.ID, id_user)))
            actions.move_to_element(campo_user).click().perform()
            campo_user.clear()
            campo_user.send_keys(usuario)

            # 2. OK Inicial
            status.info("▶️ Confirmando usuário...")
            id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
            self.driver.find_element(By.ID, id_btn_ok).click()
            
            # O SEGREDO: Delay fixo simples
            status.info("⏳ Aguardando carregamento...")
            time.sleep(3)

            # 3. Senha
            status.info("🔒 Inserindo senha...")
            try:
                xpath_senha = "//input[@type='password']"
                self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
                
                campo_senha = self.driver.find_element(By.XPATH, xpath_senha)
                actions.move_to_element(campo_senha).click().perform()
                campo_senha.clear()
                campo_senha.send_keys(senha)
                time.sleep(1)
                
                # Envia ENTER ao invés de clicar no botão
                campo_senha.send_keys(Keys.RETURN)
            except Exception as e:
                # Se falhar aqui, pode ser que já tenha logado ou erro grave
                if DEBUG_MODE:
                    st.warning(f"Aviso no passo de senha: {e}")
                pass

            # 4. Validação
            status.info("🔍 Validando acesso...")
            
            # Aguarda o campo de busca da próxima página
            self.wait.until(EC.presence_of_element_located(
                (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
            ))
            
            status.empty()
            st.success("✅ Login realizado com sucesso!")
            return True

        except Exception as e:
            status.empty()
            st.error("❌ Erro no login.")
            if DEBUG_MODE:
                st.exception(e)
                try:
                    st.image(self.driver.get_screenshot_as_png(), caption="Erro Login")
                except:
                    pass
            return False

# =============================================================================
# LÓGICA DE CONSULTA (BASEADA NO SEU SCRIPT FUNCIONAL)
# =============================================================================
class ConsultorANTT:
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config

    def _esperar_dados(self, element_id, timeout=10):
        """Helper do script original"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                val = self.driver.find_element(By.ID, element_id).get_attribute('value')
                if val and val.strip():
                    return val
                time.sleep(0.5)
            except:
                pass
        return ""

    def processar_auto(self, auto_infracao: str) -> Dict[str, Any]:
        """Implementação exata da lógica de extração fornecida"""
        res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
        janela_main = self.driver.current_window_handle
        
        try:
            # Busca
            campo = self.wait.until(EC.element_to_be_clickable(
                (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
            ))
            campo.clear()
            campo.send_keys(auto_infracao)

            encontrou = False
            for _ in range(3):
                try:
                    btn = self.driver.find_element(
                        By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar"
                    )
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    
                    self.wait.until(EC.presence_of_element_located(
                        (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
                    ))
                    encontrou = True
                    break
                except:
                    if "Nenhum registro" in self.driver.page_source:
                        break
            
            if not encontrou:
                res['status'] = 'nao_encontrado'
                res['mensagem'] = 'Auto não localizado'
                return res

            # Clica no Editar (Popup)
            btn_edit = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0"
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn_edit)

            # Troca de Janela
            WebDriverWait(self.driver, 15).until(EC.number_of_windows_to_be(2))
            for w in self.driver.window_handles:
                if w != janela_main:
                    self.driver.switch_to.window(w)
            
            time.sleep(3)

            # Extração
            dados = {}
            try:
                # Processo
                id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
                self.wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
                
                dados['processo'] = self._esperar_dados(id_proc)
                if not dados['processo']:
                    dados['processo'] = self.driver.find_element(By.ID, id_proc).get_attribute('value')

                # Outros campos simples
                dados['data_infracao'] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao"
                ).get_attribute('value')
                
                dados['codigo'] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao"
                ).get_attribute('value')
                
                dados['fato'] = self.driver.find_element(
                    By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao"
                ).get_attribute('value')

                # Tabela de Andamentos
                try:
                    xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                    self.wait.until(EC.presence_of_element_located((By.XPATH, xp)))
                    
                    tab = self.driver.find_element(By.XPATH, xp)
                    trs = tab.find_elements(By.TAG_NAME, "tr")
                    
                    if len(trs) > 1:
                        # Pega última linha (conforme seu script)
                        tds = trs[-1].find_elements(By.TAG_NAME, "td")
                        
                        if len(tds) >= 4:
                            dados['data_andamento'] = tds[3].text
                            dados['andamento'] = tds[1].text
                        elif len(tds) >= 2:
                            dados['data_andamento'] = tds[-1].text
                            dados['andamento'] = tds[0].text
                    else:
                        dados['andamento'] = 'Sem andamentos'
                        dados['data_andamento'] = ''
                except:
                    dados['andamento'] = 'Erro Tabela'
                    dados['data_andamento'] = ''

                res['status'] = 'sucesso'
                res['dados'] = dados
                res['mensagem'] = 'Sucesso'

            except Exception as e:
                res['mensagem'] = f'Erro leitura: {e}'
            
            # Fechar Popup
            try:
                self.driver.close()
            except:
                pass
            self.driver.switch_to.window(janela_main)
            return res

        except Exception as e:
            res['mensagem'] = f'Erro fluxo: {str(e)[:50]}'
            if len(self.driver.window_handles) > 1:
                try:
                    self.driver.switch_to.window(janela_main)
                except:
                    pass
            return res

# =============================================================================
# FLUXO PRINCIPAL (STREAMLIT)
# =============================================================================
def processar_planilha(arquivo, usuario: str, senha: str, config: Config):
    try:
        # Carregar Excel
        df = pd.read_excel(arquivo)
        if config.col_auto not in df.columns:
            st.error(f"❌ Coluna '{config.col_auto}' não encontrada!")
            return

        # Preparar colunas
        cols_novas = [config.col_processo, config.col_data, config.col_codigo, 
                      config.col_fato, config.col_andamento, config.col_data_andamento, config.col_status]
        for col in cols_novas:
            if col not in df.columns: df[col] = ""
        
        df = df.astype(object).replace('nan', '').fillna('')
        df_filtrado = df[df[config.col_auto].astype(str).str.strip() != '']
        total = len(df_filtrado)
        
        if total == 0:
            st.warning("Nenhum auto encontrado.")
            return

        st.info(f"Iniciando processamento de {total} autos...")
        
        # Iniciar WebDriver
        driver = WebDriverManager.criar_driver(headless=not DEBUG_MODE)
        wait = WebDriverWait(driver, 20)
        
        # Login
        login_manager = LoginManager(driver, wait, config)
        if not login_manager.realizar_login(usuario, senha):
            driver.quit()
            return

        # Processamento
        consultor = ConsultorANTT(driver, wait, config)
        
        prog_bar = st.progress(0)
        status_txt = st.empty()
        preview = st.empty()
        
        sucesso = 0
        erros = 0
        
        for idx, (original_idx, row) in enumerate(df_filtrado.iterrows()):
            auto = str(row[config.col_auto]).strip()
            status_txt.text(f"Processando {idx+1}/{total}: {auto}")
            
            res = consultor.processar_auto(auto)
            
            df.at[original_idx, config.col_status] = res['mensagem']
            if res['status'] == 'sucesso':
                d = res['dados']
                df.at[original_idx, config.col_processo] = d.get('processo', '')
                df.at[original_idx, config.col_data] = d.get('data_infracao', '')
                df.at[original_idx, config.col_codigo] = d.get('codigo', '')
                df.at[original_idx, config.col_fato] = d.get('fato', '')
                df.at[original_idx, config.col_andamento] = d.get('andamento', '')
                df.at[original_idx, config.col_data_andamento] = d.get('data_andamento', '')
                sucesso += 1
            else:
                erros += 1
            
            prog_bar.progress((idx + 1) / total)
            
            # Preview simples
            if idx % 5 == 0:
                preview.dataframe(df[[config.col_auto, config.col_status]].tail())

        driver.quit()
        st.success(f"Concluído! Sucessos: {sucesso} | Erros/Não enc.: {erros}")
        
        # Download
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        st.download_button("📥 Baixar Resultado", output, "ANTT_Resultado.xlsx")

    except Exception as e:
        st.error(f"Erro geral: {e}")

# =============================================================================
# INTERFACE
# =============================================================================
def main():
    st.title("🚛 Robô ANTT - Script Validado")
    
    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")
    arquivo = st.file_uploader("Upload Excel", type=['xlsx'])
    
    if st.button("Iniciar") and usuario and senha and arquivo:
        config = Config()
        processar_planilha(arquivo, usuario, senha, config)

if __name__ == "__main__":
    main()
