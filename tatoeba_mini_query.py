import requests

def query_one_example(word, from_lang="eng", to_lang="cmn"):
    url = f"https://tatoeba.org/en/api_v0/search?from={from_lang}&query={word}&to={to_lang}"
    resp = requests.get(url)
    if resp.status_code != 200:
        return None

    data = resp.json()
    results = data.get("results", [])
    if not results:
        return None

    item = results[0]
    example_sentence = item.get("text")
    translations = item.get("translations", [])
    example_chinese = translations[0][0]["text"] if translations and translations[0] else None

    return {
        "example_sentence": example_sentence,
        "example_chinese": example_chinese
    }

if __name__ == "__main__":
    word = input("请输入单词: ")
    result = query_one_example(word)
    if result:
        print(result)
    else:
        print("未找到例句")