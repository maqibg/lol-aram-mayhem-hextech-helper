import time
import random
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException

# ==========================================
# 配置与初始化
# ==========================================
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # 强制中文环境
    chrome_options.add_argument("--lang=zh-CN")
    chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'zh-CN,zh;q=0.9'})
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# ==========================================
# 从当前页面提取海克斯名称列表（按DOM顺序）
# ==========================================
def extract_augment_names(driver):
    """提取当前Tab下所有海克斯名称，按页面排名顺序返回列表"""
    names = []
    try:
        # 等待列表加载
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "strong.text-sm.text-gray-900"))
        )
        time.sleep(0.8)
        
        # 滚动加载所有内容（处理懒加载）
        last_count = 0
        for _ in range(10):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
            current_count = len(driver.find_elements(By.CSS_SELECTOR, "strong.text-sm.text-gray-900"))
            if current_count == last_count:
                break
            last_count = current_count
        
        # 回到顶部
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.3)
        
        elements = driver.find_elements(By.CSS_SELECTOR, "strong.text-sm.text-gray-900")
        for el in elements:
            txt = el.text.strip()
            if txt and len(txt) >= 2:
                names.append(txt)
    except TimeoutException:
        print("   > 等待海克斯列表超时")
    except Exception as e:
        print(f"   > 提取海克斯名称异常: {e}")
    return names

# ==========================================
# 点击指定的 Tab 按钮
# ==========================================
def click_tier_tab(driver, tab_text):
    """点击指定文本的Tab按钮（全部/白银/黄金/棱彩）"""
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if btn.text.strip() == tab_text:
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.5)  # 等待内容刷新
                return True
        print(f"   > 未找到按钮: {tab_text}")
        return False
    except Exception as e:
        print(f"   > 点击Tab异常 ({tab_text}): {e}")
        return False

# ==========================================
# 单个英雄抓取逻辑 (数据源: OP.GG)
# ==========================================
def scrape_single_champion(driver, cn_name, en_name):
    url = f"https://op.gg/zh-cn/lol/modes/aram-mayhem/{en_name}/augments"
    print(f"[{cn_name}] 正在处理: {url}")
    
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2.5)

        # 1. 关闭可能的弹窗/Cookie 同意框
        try:
            driver.execute_script("""
            document.querySelectorAll('[class*="consent"], [class*="cookie"]').forEach(el => el.remove());
            document.querySelectorAll('button').forEach(b => {
                var t = (b.textContent || '').toLowerCase();
                if (t.includes('agree') || t.includes('accept') || t.includes('同意')) b.click();
            });
            """)
        except: pass
        
        time.sleep(1)

        # 2. 点击「全部」Tab，获取总排名
        print(f"   > 正在提取「全部」排名...")
        click_tier_tab(driver, "全部")
        all_names = extract_augment_names(driver)
        print(f"   > 「全部」共 {len(all_names)} 个海克斯")
        
        # 构建总排名映射: name -> overall_rank (1-based)
        overall_rank_map = {}
        for idx, name in enumerate(all_names, 1):
            if name not in overall_rank_map:
                overall_rank_map[name] = idx

        # 3. 依次点击各等级Tab，提取等级内排名
        tier_data = {}  # name -> {"tier": ..., "t_rank": ...}
        
        for tier_name in ["白银", "黄金", "棱彩"]:
            print(f"   > 正在提取「{tier_name}」排名...")
            if click_tier_tab(driver, tier_name):
                tier_names = extract_augment_names(driver)
                print(f"   > 「{tier_name}」共 {len(tier_names)} 个海克斯")
                for idx, name in enumerate(tier_names, 1):
                    if name not in tier_data:
                        tier_data[name] = {"tier": tier_name, "t_rank": idx}
            time.sleep(0.5)

        # 4. 合并数据
        valid_augments = []
        seen = set()
        
        # 以全部列表为基准，保证每个海克斯都有数据
        for name in all_names:
            if name in seen:
                continue
            seen.add(name)
            
            info = tier_data.get(name, {"tier": "未知", "t_rank": 999})
            o_rank = overall_rank_map.get(name, 999)
            
            valid_augments.append({
                "name": name,
                "tier": info["tier"],
                "overall_rank": o_rank,
                "t_rank": info["t_rank"]
            })
        
        # 补充只出现在等级Tab但不在「全部」中的海克斯
        for name, info in tier_data.items():
            if name not in seen:
                seen.add(name)
                valid_augments.append({
                    "name": name,
                    "tier": info["tier"],
                    "overall_rank": 999,
                    "t_rank": info["t_rank"]
                })

        status_code = "clean" if valid_augments else "empty"
        return valid_augments, status_code

    except Exception as e:
        print(f"[{cn_name}] 异常: {e}")
        return [], "error"

# ==========================================
# 批量抓取入口
# ==========================================
def crawl_champions(target_list):
    """
    直接返回内存字典，不再写临时文件
    """
    print(f"--- 开始抓取 {len(target_list)} 个英雄 ---")
    
    driver = setup_driver()
    failed_list = []
    success_data = {} 
    
    MAX_RETRIES = 3 

    try:
        total = len(target_list)
        for i, (cn_name, en_name) in enumerate(target_list, 1):
            print(f"--- 进度 [{i}/{total}] : {cn_name} ---")
            
            # 定期重启浏览器释放内存，防止 OOM 崩溃
            if i > 1 and i % 15 == 0:
                print("   > [系统] 定期重启浏览器释放资源...")
                try: driver.quit()
                except: pass
                driver = setup_driver()
            
            for attempt in range(1, MAX_RETRIES + 1):
                data, status = scrape_single_champion(driver, cn_name, en_name)
                
                if status == "clean" and data:
                    # 成功！直接存入内存字典
                    success_data[cn_name] = data
                    print(f"   > 成功抓取 {len(data)} 条")
                    break 
                else:
                    print(f"   > 数据为空 (状态: {status})，重试 ({attempt})")
                    # 检查浏览器是否存活，如果不能连了就直接重启
                    try:
                        _ = driver.title
                    except Exception:
                        print(f"   > 浏览器连接断开，重启中...")
                        try: driver.quit()
                        except: pass
                        driver = setup_driver()
                
                if attempt < MAX_RETRIES:
                    time.sleep(2)
                else:
                    print(f"   > ❌ {cn_name} 失败")
                    failed_list.append(cn_name)

            time.sleep(random.uniform(1.2, 2.0))
            
    finally:
        driver.quit()
        print(f"--- 爬取阶段结束 ---")
        
    return success_data, failed_list

if __name__ == "__main__":
    # 测试代码
    res, fail = crawl_champions([("复仇焰魂", "Brand")])
    print(res)