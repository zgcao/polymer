all:
	python setup.py build_ext --inplace

clean:
	rm -fv *.html
	rm -fv *.pyc
	rm -fv *.c
	rm -fv *.so
