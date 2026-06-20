# ABOUTME: Tests that the base template wires up vendored CSS assets correctly.
# ABOUTME: Pico must load before style.css so our overrides win the cascade.


class TestBaseAssets:
    def test_pico_linked_before_style(self, client):
        html = client.get("/books").data.decode()
        pico = html.find("pico.min.css")
        style = html.find("style.css")
        assert pico != -1, "base template must link pico.min.css"
        assert style != -1, "base template must link style.css"
        assert pico < style, "pico.min.css must load before style.css for override order"

    def test_pico_asset_is_served(self, client):
        resp = client.get("/static/pico.min.css")
        assert resp.status_code == 200
